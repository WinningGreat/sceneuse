import AppKit
import CoreImage
import CoreVideo
import Foundation

enum Tiles {
    static let maxLongSide: CGFloat = 512
    static let coverageSkip = 0.6
    static let maxDisplayFraction = 0.40

    private static let ci = CIContext(options: [.useSoftwareRenderer: false])

    static func encode(
        buffer: CVPixelBuffer,
        dirtyPixels: [CGRect],
        scale: CGFloat,
        displayLogical: Rect,
        nodes: [NodeInfo],
        enabled: Bool
    ) -> (logicalDamage: [Rect], tiles: [TileInfo]) {
        let damage = dirtyPixels.map { Coord.pixelRectToLogical($0, scale: scale, displayLogical: displayLogical) }
            .filter { $0.w >= 1 && $0.h >= 1 }

        guard enabled else { return (damage, []) }

        let displayArea = displayLogical.area
        let usable = nodes.filter { AXSnap.usable($0) && $0.bounds != nil }
        var tiles: [TileInfo] = []

        for (pixelRect, logical) in zip(dirtyPixels, damage) {
            if displayArea > 0, logical.area >= displayArea * maxDisplayFraction {
                continue
            }
            if covered(logical, by: usable) {
                continue
            }
            if let tile = jpeg(buffer: buffer, pixelRect: pixelRect, logical: logical) {
                tiles.append(tile)
            }
            if tiles.count >= 8 { break }
        }
        return (damage, tiles)
    }

    private static func covered(_ rect: Rect, by nodes: [NodeInfo]) -> Bool {
        guard !nodes.isEmpty else { return false }
        for n in nodes {
            guard let b = n.bounds else { continue }
            if rect.coverage(of: b) >= coverageSkip { return true }
            if b.cg.insetBy(dx: -2, dy: -2).contains(rect.center) { return true }
        }
        return false
    }

    private static func jpeg(buffer: CVPixelBuffer, pixelRect: CGRect, logical: Rect) -> TileInfo? {
        let ciImage = CIImage(cvPixelBuffer: buffer)
        let cropped = ciImage.cropped(to: pixelRect)
        if cropped.extent.isEmpty { return nil }

        var image = cropped
        let longSide = max(pixelRect.width, pixelRect.height)
        if longSide > maxLongSide {
            let s = maxLongSide / longSide
            image = cropped.transformed(by: CGAffineTransform(scaleX: s, y: s))
        }

        guard let cg = ci.createCGImage(image, from: image.extent) else { return nil }
        let rep = NSBitmapImageRep(cgImage: cg)
        guard let data = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.55]) else {
            return nil
        }
        return TileInfo(rect: logical, mime: "image/jpeg", data: data.base64EncodedString())
    }
}
