import Foundation
import ScreenCaptureKit
import CoreMedia
import CoreVideo
import AppKit

protocol CaptureDelegate: AnyObject {
    func captureDidProduce(
        dirtyPixels: [CGRect],
        scale: CGFloat,
        buffer: CVPixelBuffer?,
        contentRect: CGRect
    )
    func captureDidFail(_ error: Error)
}

/// ScreenCaptureKit stream: compositor-adjacent frames + dirtyRects. Not a user screenshot tool.
final class CaptureSession: NSObject, SCStreamDelegate, SCStreamOutput {
    weak var delegate: CaptureDelegate?

    private var stream: SCStream?
    private let outputQueue = DispatchQueue(label: "dev.sceneuse.capture", qos: .userInitiated)
    private var running = false
    private var sentKeyframe = false
    private static var loggedAttach = false

    var isRunning: Bool { running }

    func start() {
        outputQueue.async { [weak self] in
            guard let self, !self.running else { return }
            Task { await self.startAsync() }
        }
    }

    func stop() {
        outputQueue.async { [weak self] in
            guard let self else { return }
            self.running = false
            let stream = self.stream
            self.stream = nil
            Task {
                try? await stream?.stopCapture()
            }
        }
    }

    private func startAsync() async {
        do {
            if !CGPreflightScreenCaptureAccess() {
                _ = CGRequestScreenCaptureAccess()
            }
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            let displayID = CGMainDisplayID()
            guard let display = content.displays.first(where: { $0.displayID == displayID }) ?? content.displays.first else {
                return
            }

            let filter = SCContentFilter(display: display, excludingWindows: [])
            let config = SCStreamConfiguration()
            config.width = display.width
            config.height = display.height
            config.minimumFrameInterval = CMTime(value: 1, timescale: 8)
            config.queueDepth = 3
            config.showsCursor = false
            config.pixelFormat = kCVPixelFormatType_32BGRA
            if #available(macOS 13.0, *) {
                config.capturesAudio = false
            }

            let stream = SCStream(filter: filter, configuration: config, delegate: self)
            try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: outputQueue)
            try await stream.startCapture()
            self.stream = stream
            self.running = true
            self.sentKeyframe = false
        } catch {
            delegate?.captureDidFail(error)
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        running = false
        delegate?.captureDidFail(error)
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen else { return }
        guard let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
              let info = attachments.first else { return }

        if let statusRaw = info[.status] as? Int,
           let status = SCFrameStatus(rawValue: statusRaw),
           status != .complete {
            return
        }

        let scale = (info[.scaleFactor] as? CGFloat) ?? NSScreen.main?.backingScaleFactor ?? 2
        var content = CGRect(x: 0, y: 0, width: 1, height: 1)
        if let dict = info[.contentRect] as? NSDictionary,
           let r = CGRect(dictionaryRepresentation: dict) {
            content = r
        } else if let value = info[.contentRect] as? NSValue {
            content = value.rectValue
        }

        var dirty = Self.rects(from: info[.dirtyRects])
        let buffer = sampleBuffer.imageBuffer
        if !Self.loggedAttach {
            Self.loggedAttach = true
            let raw = info[.dirtyRects]
            let kind = raw == nil ? "nil" : String(describing: Swift.type(of: raw!))
            let bw = buffer.map { CVPixelBufferGetWidth($0) } ?? 0
            let bh = buffer.map { CVPixelBufferGetHeight($0) } ?? 0
            fputs("sceneused capture frame dirtyType=\(kind) parsed=\(dirty.count) buffer=\(bw)x\(bh) scale=\(scale)\n", stderr)
        }
        // First complete frame often omits dirtyRects. Treat that once as a keyframe
        // so the client sees compositor bounds; later idle frames stay empty.
        if dirty.isEmpty, !sentKeyframe, let buffer {
            let w = CVPixelBufferGetWidth(buffer)
            let h = CVPixelBufferGetHeight(buffer)
            if w > 0, h > 0 {
                dirty = [CGRect(x: 0, y: 0, width: w, height: h)]
            }
        }
        if buffer != nil { sentKeyframe = true }
        delegate?.captureDidProduce(dirtyPixels: dirty, scale: scale, buffer: buffer, contentRect: content)
    }

    private static func rects(from value: Any?) -> [CGRect] {
        guard let value else { return [] }
        if let values = value as? [NSValue] {
            return values.map(\.rectValue)
        }
        if let dicts = value as? [NSDictionary] {
            return dicts.compactMap { CGRect(dictionaryRepresentation: $0) }
        }
        if let arr = value as? [Any] {
            return arr.compactMap { item in
                if let v = item as? NSValue { return v.rectValue }
                if let d = item as? NSDictionary { return CGRect(dictionaryRepresentation: d) }
                return nil
            }
        }
        return []
    }
}
