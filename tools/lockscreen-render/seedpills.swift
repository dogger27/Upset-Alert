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
                // THREE DIGITS AT THE LOCK SCREEN'S OWN TEXT SIZE. The Lock Screen
                // renders .caption larger than a default-size preview does, and
                // 32pt truncated "126" to "1…". The box is sized for three bold
                // digits at that size; the number tightens and, past that,
                // shrinks — it is never truncated, because a rank cut to "1…"
                // says nothing. Fixed width, so every name starts at the same x.
                Text("\(value)")
                    .font(.caption).fontWeight(.bold)
                    .foregroundColor(isSeed ? seedInk : rankInk)
                    .monospacedDigit()
                    .lineLimit(1)
                    .allowsTightening(true)
                    .minimumScaleFactor(0.6)
                    .padding(.horizontal, 2)
                    .frame(width: 38, height: 22)
                    .background(RoundedRectangle(cornerRadius: 4).fill(isSeed ? seedBg : rankBg))
                    .overlay(RoundedRectangle(cornerRadius: 4).stroke(isSeed ? seedLine : rankLine, lineWidth: 0.5))
            } else {
                // No number at all still reserves the column, or the two names
                // would start at different x.
                Color.clear.frame(width: 38, height: 22)
            }
        }
    }
}


struct Row: View {
    let seed: Int?; let rank: Int?; let name: String
    var body: some View {
        HStack(spacing: 8) { SeedBadge(seed: seed, drawRank: rank); Text(name).font(.system(size: 17, weight: .semibold)).foregroundColor(.white) }
    }
}
struct Sheet: View {
    var body: some View {
        HStack(alignment: .top, spacing: 28) {
            ForEach([("default", ContentSizeCategory.large), ("xxxLarge", .extraExtraExtraLarge), ("AX2", .accessibilityLarge)], id: \.0) { pair in
                VStack(alignment: .leading, spacing: 10) {
                    Text(pair.0).font(.caption).foregroundColor(.gray)
                    Row(seed: nil, rank: 126, name: "Gaël Monfils")
                    Row(seed: 14, rank: nil, name: "Learner Tien")
                    Row(seed: 6, rank: nil, name: "Alex de Minaur")
                    Row(seed: nil, rank: 110, name: "Arthur Géa")
                    Row(seed: 128, rank: nil, name: "Long seed")
                }.environment(\.sizeCategory, pair.1)
            }
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
