import SwiftUI

struct RootView: View {
    @EnvironmentObject private var store: AppStore
    @State private var tab = 0

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()

            VStack(spacing: 10) {
                header
                connectionCard

                Picker("Bagian", selection: $tab) {
                    Text("Kontrol").tag(0)
                    Text("Efek").tag(1)
                    Text("miIO").tag(2)
                    Text("Info").tag(3)
                }
                .pickerStyle(.segmented)

                if store.lanControlBlocked {
                    lanBanner
                }

                ScrollView {
                    VStack(spacing: 12) {
                        switch tab {
                        case 1:
                            EffectsView()
                        case 2:
                            DiagnosticsView()
                        case 3:
                            InfoView()
                        default:
                            ControlView()
                        }
                    }
                    .padding(.bottom, 24)
                }
                .scrollDismissesKeyboard(.interactively)
            }
            .padding(.horizontal, 14)
            .padding(.top, 6)
        }
        .task {
            await store.bootstrap()
        }
    }

    // MARK: - Header

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 2) {
                Text("yeelight")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Theme.fg)
                Text("YLDP06YL · kontrol lokal, tanpa cloud")
                    .font(.caption)
                    .foregroundStyle(Theme.muted)
            }
            Spacer()
            Text(store.statusText)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(store.statusColor)
                .lineLimit(1)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(Theme.panel2)
                .clipShape(Capsule())
        }
    }

    // MARK: - Koneksi

    private var connectionCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text("IP")
                    .font(.caption)
                    .foregroundStyle(Theme.muted)
                    .frame(width: 38, alignment: .leading)
                TextField("192.168.1.20", text: $store.ip)
                    .keyboardType(.numbersAndPunctuation)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .fieldStyle()
                Text("Port")
                    .font(.caption)
                    .foregroundStyle(Theme.muted)
                TextField("55443", text: $store.portText)
                    .keyboardType(.numberPad)
                    .frame(width: 62)
                    .fieldStyle()
            }

            HStack(spacing: 8) {
                Text("Subnet")
                    .font(.caption)
                    .foregroundStyle(Theme.muted)
                    .frame(width: 38, alignment: .leading)
                TextField("kosong = semua jaringan lokal", text: $store.subnet)
                    .keyboardType(.numbersAndPunctuation)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .fieldStyle()
            }

            HStack(spacing: 8) {
                Button {
                    Task { await store.scan() }
                } label: {
                    Text(store.scanLabel)
                }
                .buttonStyle(GhostButtonStyle())
                .disabled(store.scanning)

                Button {
                    if store.isConnected {
                        Task { await store.disconnect() }
                    } else {
                        Task { await store.connect() }
                    }
                } label: {
                    Text(store.isConnected ? "Putuskan" : "Hubungkan")
                }
                .buttonStyle(PrimaryButtonStyle(tint: store.isConnected ? Theme.red.opacity(0.85) : Theme.accent))
            }

            if store.scanning {
                ProgressView(value: store.progressValue)
                    .tint(Theme.accent)
            }

            if !store.hits.isEmpty {
                Text("Ditemukan \(store.hits.count) host")
                    .font(.caption2)
                    .foregroundStyle(Theme.muted)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(store.hits) { hit in
                            Button {
                                store.ip = hit.ip
                            } label: {
                                HStack(spacing: 6) {
                                    Circle()
                                        .fill(hit.isBulb ? Theme.green : Theme.muted.opacity(0.5))
                                        .frame(width: 7, height: 7)
                                    Text(hit.isBulb ? (hit.name.isEmpty ? hit.ip : "\(hit.name) · \(hit.ip)") : hit.ip)
                                        .font(.caption)
                                        .foregroundStyle(store.ip == hit.ip ? Color.black : Theme.fg)
                                }
                                .padding(.horizontal, 10)
                                .padding(.vertical, 7)
                                .background(store.ip == hit.ip ? Theme.accent : Theme.panel2)
                                .clipShape(Capsule())
                            }
                        }
                    }
                }
            }
        }
        .padding(12)
        .background(Theme.panel)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }

    private var lanBanner: some View {
        HStack(spacing: 10) {
            Image(systemName: "lock.trianglebadge.exclamationmark")
                .foregroundStyle(Theme.accent)
            Text("LAN Control mati di lampu ini.")
                .font(.caption)
                .foregroundStyle(Theme.fg)
            Spacer()
            Button("Buka") { tab = 2 }
                .font(.caption.weight(.semibold))
                .foregroundStyle(Theme.accent)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(Theme.panel2)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}
