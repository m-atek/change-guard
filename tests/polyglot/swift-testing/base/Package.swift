// swift-tools-version:6.0
// Demo project, no real data.
import PackageDescription

let package = Package(
    name: "Shop",
    targets: [
        .target(name: "Shop"),
        .testTarget(name: "ShopTests", dependencies: ["Shop"]),
    ]
)
