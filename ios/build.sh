#!/usr/bin/env bash
# Bangun IPA unsigned untuk sideloading. Jalankan di macOS dengan Xcode.
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="Yeelight"
VERSION="0.1.0"
BUILD_DIR="build"
DIST_DIR="$(cd .. && pwd)/dist"
IPA="$DIST_DIR/yeelight-ios-$VERSION.ipa"

info() { printf '\033[1;33m%s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m%s\033[0m\n' "$*" >&2; exit 1; }

command -v xcodebuild >/dev/null 2>&1 || fail "xcodebuild tidak ditemukan. Pasang Xcode dari App Store dulu."
command -v xcrun >/dev/null 2>&1 || fail "xcrun tidak ditemukan. Jalankan: xcode-select --install"

info "==> Versi Xcode"
xcodebuild -version

if ! command -v xcodegen >/dev/null 2>&1; then
  info "==> xcodegen belum terpasang"
  if command -v brew >/dev/null 2>&1; then
    brew install xcodegen
  else
    fail "Homebrew belum ada. Install dari https://brew.sh lalu jalankan: brew install xcodegen"
  fi
fi

info "==> Membuat Yeelight.xcodeproj"
xcodegen generate

info "==> Build Release tanpa signing"
rm -rf "$BUILD_DIR"
xcodebuild \
  -project Yeelight.xcodeproj \
  -scheme Yeelight \
  -configuration Release \
  -sdk iphoneos \
  -derivedDataPath "$BUILD_DIR" \
  CODE_SIGN_IDENTITY="" \
  CODE_SIGNING_REQUIRED=NO \
  CODE_SIGNING_ALLOWED=NO \
  build

APP_PATH="$BUILD_DIR/Build/Products/Release-iphoneos/$APP_NAME.app"
[ -d "$APP_PATH" ] || fail "Build selesai tetapi $APP_PATH tidak ada."

info "==> Mengemas IPA"
rm -rf "$BUILD_DIR/Payload"
mkdir -p "$BUILD_DIR/Payload"
cp -R "$APP_PATH" "$BUILD_DIR/Payload/"
mkdir -p "$DIST_DIR"
rm -f "$IPA"
(cd "$BUILD_DIR" && zip -qry "$IPA" Payload)

info "==> Selesai"
echo "IPA : $IPA"
ls -lh "$IPA"
echo
echo "Langkah selanjutnya:"
echo "  1. Buka Sideloadly (atau AltStore) di Mac, sambungkan iPhone."
echo "  2. Seret IPA ke Sideloadly, masuk dengan Apple ID gratis Anda."
echo "  3. Setelah terpasang: Settings > Privacy & Security > Local Network > Yeelight = ON."
