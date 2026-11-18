// swift-tools-version:5.9
// Demo project, no real data.
import PackageDescription

let package = Package(
    name: "Shop",
    targets: [
        .target(name: "Shop"),
        .testTarget(name: "ShopTests", dependencies: ["Shop"]),
    ]
)
