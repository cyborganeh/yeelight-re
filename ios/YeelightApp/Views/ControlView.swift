import SwiftUI

struct ControlView: View {
    @EnvironmentObject private var store: AppStore

    @State private var brightness: Double = 100
    @State private var colorTemperature: Double = 4000
    @State private var hue: Double = 0
    @State private var saturation: Double = 0
    @State private var pickerColor = Color.white
    @State private var editingBrightness = false
    @State private var editingTemperature = false

    private let swatches: [Int] = [
        0xFF3B30, 0xFF9500, 0xFFCC00, 0x34C759, 0x00C7BE,
        0x007AFF, 0x5856D6, 0xAF52DE, 0xFF2D55, 0xFFFFFF,
    ]

    var body: some View {
        VStack(spacing: 12) {
            powerCard
            brightnessCard
            colorCard
            temperatureCard
        }
        .onAppear { syncFromStore() }
        .onChange(of: store.state) { _ in syncFromStore() }
    }

    private func syncFromStore() {
        let current = store.state
        if !editingBrightness {
            brightness = Double(max(1, current.bright))
        }
        if !editingTemperature {
            colorTemperature = Double(current.ct)
        }
        pickerColor = Color(hex: UInt32(current.rgb & 0xFFFFFF))
        hue = Double(current.hue)
        saturation = Double(current.sat)
    }

    // MARK: - Daya

    private var powerCard: some View {
        Card("Daya & kecerahan", subtitle: "Kontrol utama lampu") {
            Button {
                store.setPower(!store.state.isOn)
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: store.state.isOn ? "sun.max.fill" : "moon.fill")
                    Text(store.state.isOn ? "Matikan lampu" : "Nyalakan lampu")
                }
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(Color.black.opacity(0.85))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(store.state.isOn ? Theme.green : Theme.muted)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .disabled(!store.isConnected)
            .opacity(store.isConnected ? 1 : 0.5)

            HStack {
                Text("Kecerahan")
                    .font(.subheadline)
                    .foregroundStyle(Theme.muted)
                Spacer()
                Text("\(Int(brightness))%")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.fg)
            }

            Slider(
                value: $brightness,
                in: 1...100,
                step: 1,
                onEditingChanged: { editing in
                    editingBrightness = editing
                    if !editing {
                        store.setBright(Int(brightness))
                    }
                }
            )
            .tint(Theme.accent)

            HStack(spacing: 8) {
                ForEach([10, 25, 50, 75, 100], id: \.self) { preset in
                    Button("\(preset)%") {
                        brightness = Double(preset)
                        store.setBright(preset)
                    }
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Theme.fg)
                    .padding(.vertical, 7)
                    .frame(maxWidth: .infinity)
                    .background(Theme.panel2)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
            }
            .disabled(!store.isConnected)
            .opacity(store.isConnected ? 1 : 0.5)
        }
    }

    // MARK: - Warna

    private var colorCard: some View {
        Card("Warna", subtitle: "RGB, swatch, atau HSV") {
            HStack(spacing: 12) {
                ColorPicker("Pilih warna", selection: $pickerColor, supportsOpacity: false)
                    .labelsHidden()
                    .frame(width: 46, height: 46)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

                VStack(alignment: .leading, spacing: 2) {
                    Text(Proto.hex(pickerColor.rgbInt))
                        .font(.system(.subheadline, design: .monospaced).weight(.semibold))
                        .foregroundStyle(Theme.fg)
                    Text("mode \(store.state.modeText)")
                        .font(.caption2)
                        .foregroundStyle(Theme.muted)
                }

                Spacer()

                Button("Terapkan") {
                    store.setRGB(pickerColor.rgbInt)
                }
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.black.opacity(0.85))
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Theme.accent)
                .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
            }

            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 5), spacing: 8) {
                ForEach(swatches, id: \.self) { value in
                    Button {
                        store.setRGB(value)
                    } label: {
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(Color(hex: UInt32(value)))
                            .frame(height: 34)
                            .overlay(
                                RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .stroke(Theme.border, lineWidth: 1)
                            )
                    }
                }
            }
            .disabled(!store.isConnected)
            .opacity(store.isConnected ? 1 : 0.5)

            Divider().overlay(Theme.border)

            HStack(spacing: 10) {
                labelled("H", value: "\(Int(hue))")
                Slider(value: $hue, in: 0...359, step: 1)
                    .tint(Theme.accent)
                labelled("S", value: "\(Int(saturation))")
                Slider(value: $saturation, in: 0...100, step: 1)
                    .tint(Theme.accent)
            }

            Button("Terapkan HSV") {
                store.setHSV(hue: Int(hue), sat: Int(saturation))
            }
            .buttonStyle(GhostButtonStyle())
            .disabled(!store.isConnected)
            .opacity(store.isConnected ? 1 : 0.5)
        }
    }

    // MARK: - Suhu warna

    private var temperatureCard: some View {
        Card("Suhu warna", subtitle: "Putih hangat 1700 K sampai dingin 6500 K") {
            HStack {
                Text("\(Int(colorTemperature)) K")
                    .font(.system(.subheadline, design: .monospaced).weight(.semibold))
                    .foregroundStyle(Theme.fg)
                Spacer()
                Text(colorTemperature < 3000 ? "hangat" : (colorTemperature > 5000 ? "dingin" : "netral"))
                    .font(.caption)
                    .foregroundStyle(Theme.muted)
            }

            Slider(
                value: $colorTemperature,
                in: 1700...6500,
                step: 50,
                onEditingChanged: { editing in
                    editingTemperature = editing
                    if !editing {
                        store.setCT(Int(colorTemperature))
                    }
                }
            )
            .tint(Theme.accent)

            HStack(spacing: 8) {
                ForEach([1900, 2700, 4000, 5000, 6500], id: \.self) { kelvin in
                    Button("\(kelvin)") {
                        colorTemperature = Double(kelvin)
                        store.setCT(kelvin)
                    }
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Theme.fg)
                    .padding(.vertical, 7)
                    .frame(maxWidth: .infinity)
                    .background(Theme.panel2)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
            }
            .disabled(!store.isConnected)
            .opacity(store.isConnected ? 1 : 0.5)
        }
    }

    private func labelled(_ title: String, value: String) -> some View {
        VStack(spacing: 1) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(Theme.muted)
            Text(value)
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(Theme.fg)
        }
        .frame(width: 30)
    }
}
