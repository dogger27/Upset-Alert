import SwiftUI
import AppKit
private let seedBg   = Color(red: 0.227, green: 0.184, blue: 0.063)  // #3a2f10
private let seedInk  = Color(red: 0.910, green: 0.780, blue: 0.400)  // #e8c766
private let seedLine = Color(red: 0.420, green: 0.333, blue: 0.094)  // #6b5518
private let rankBg   = Color(red: 0.169, green: 0.227, blue: 0.208)  // #2b3a35
private let rankInk  = Color(red: 0.722, green: 0.776, blue: 0.753)  // #b8c6c0
private let rankLine = Color(red: 0.624, green: 0.690, blue: 0.663)  // #9fb0a9
private struct SeedBadge: View {
    let seed: Int?
    let drawRank: Int?

    var body: some View {
        let isSeed = seed != nil
        let value = seed ?? drawRank
        return Group {
            if let value {
                // ONE SIZE FOR EVERY NUMBER. The box was 24×16 and the type fixed,
                // so "110" ran past its own edges while "6" swam — pills of three
                // visibly different sizes on one card. The box is wider and
                // taller now, and a three-digit number shrinks a little to fit
                // it rather than overflowing; every pill is the same rectangle.
                Text("\(value)")
                    .font(.caption).fontWeight(.bold)
                    .foregroundColor(isSeed ? seedInk : rankInk)
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
                    .padding(.horizontal, 3)
                    .frame(width: 32, height: 21)
                    .background(RoundedRectangle(cornerRadius: 4).fill(isSeed ? seedBg : rankBg))
                    .overlay(RoundedRectangle(cornerRadius: 4).stroke(isSeed ? seedLine : rankLine, lineWidth: 0.5))
            } else {
                // No number at all still reserves the column, or the two names
                // would start at different x.
                Color.clear.frame(width: 32, height: 21)
            }
        }
    }
}


struct Sheet: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                SeedBadge(seed: 6, drawRank: nil); SeedBadge(seed: 31, drawRank: nil)
                SeedBadge(seed: nil, drawRank: 50); SeedBadge(seed: nil, drawRank: 66)
                SeedBadge(seed: nil, drawRank: 67); SeedBadge(seed: nil, drawRank: 110)
                SeedBadge(seed: 128, drawRank: nil); SeedBadge(seed: nil, drawRank: nil)
                Text("← blank keeps the column").font(.caption).foregroundColor(.white)
            }
            HStack(spacing: 8) { SeedBadge(seed: 31, drawRank: nil); Text("Zizou Bergs").font(.system(size: 17, weight: .semibold)).foregroundColor(.white) }
            HStack(spacing: 8) { SeedBadge(seed: nil, drawRank: 110); Text("Arthur Géa").font(.system(size: 17, weight: .semibold)).foregroundColor(.white) }
        }
        .padding(16)
        .background(Color(red: 0.12, green: 0.13, blue: 0.13))
    }
}
MainActor.assumeIsolated {
    let renderer = ImageRenderer(content: Sheet())
    renderer.scale = 3
    guard let img = renderer.nsImage, let tiff = img.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff), let png = rep.representation(using: .png, properties: [:]) else {
        print("render failed"); exit(1)
    }
    try! png.write(to: URL(fileURLWithPath: "seedpills.png"))
    print("wrote seedpills.png")
}
