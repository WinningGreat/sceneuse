// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "sceneused",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "sceneused", targets: ["sceneused"]),
    ],
    targets: [
        .executableTarget(
            name: "sceneused",
            path: "Sources/sceneused"
        ),
    ]
)
