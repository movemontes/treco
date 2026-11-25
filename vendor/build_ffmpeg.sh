#!/bin/bash
# Monta o ffmpeg do Treco para Macs com chip Apple (M1 ou mais novo), com whisper e libass.
# Uso: vendor/build_ffmpeg.sh PASTA_DE_TRABALHO_SEM_ESPACOS
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
B="${1:?informe uma pasta de trabalho sem espacos}"
case "$B" in *" "*) echo "A pasta de trabalho nao pode ter espacos"; exit 2;; esac

FFMPEG_V=9.1
WHISPER_V=v1.9.6
X264_COMMIT=b35605ace3ddf7c1a5d67a2eb553f034aef41d55
LAME_V=3.100
OPUS_V=1.6.1
OGG_V=1.3.6
VORBIS_V=1.3.7
VPX_V=v1.17.0
FREETYPE_V=VER-2-15-0
FRIBIDI_V=v1.0.18
HARFBUZZ_V=15.2.0
LIBASS_V=0.17.5

P="$B/prefix"; S="$B/src"; L="$B/logs"; T="$B/tools"
mkdir -p "$P" "$S" "$L"
export MACOSX_DEPLOYMENT_TARGET=13.0
export CFLAGS="-O2 -arch arm64 -mmacosx-version-min=13.0 -I$P/include"
export CXXFLAGS="$CFLAGS"
export LDFLAGS="-arch arm64 -mmacosx-version-min=13.0 -L$P/lib"
export PKG_CONFIG_PATH="$P/lib/pkgconfig"
export PKG_CONFIG_LIBDIR="$P/lib/pkgconfig"
JOBS="$(sysctl -n hw.ncpu)"

[ -x "$T/bin/meson" ] || { /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m venv "$T"; "$T/bin/pip" install -q meson ninja cmake pkgconf; }
export PATH="$T/bin:$PATH"
export PKG_CONFIG="$T/bin/pkgconf"

step() { # nome, função: pula o que já foi montado
  if [ -f "$B/.done-$1" ]; then echo "ja pronto: $1"; return; fi
  echo "montando: $1 ($(date +%H:%M:%S))"
  if ! "$2" > "$L/$1.log" 2>&1; then echo "ERRO em $1:"; tail -25 "$L/$1.log"; exit 1; fi
  touch "$B/.done-$1"
}
tarball() { # url pasta
  [ -d "$S/$2" ] && return 0
  local file="$S/$(basename "$1")"
  [ -f "$file" ] || curl -fsSL --retry 3 -o "$file" "$1"
  tar -xf "$file" -C "$S"
}
clone() { # url tag pasta
  [ -d "$S/$3" ] || git -c advice.detachedHead=false clone -q --depth 1 --branch "$2" "$1" "$S/$3"
}

b_lame() {
  tarball "https://downloads.sourceforge.net/project/lame/lame/$LAME_V/lame-$LAME_V.tar.gz" "lame-$LAME_V"
  cd "$S/lame-$LAME_V"
  sed -i '' '/lame_init_old/d' include/libmp3lame.sym
  ./configure --prefix="$P" --host=aarch64-apple-darwin --disable-shared --enable-static --disable-frontend --disable-decoder
  make -j"$JOBS" install
}
b_ogg() {
  tarball "https://downloads.xiph.org/releases/ogg/libogg-$OGG_V.tar.gz" "libogg-$OGG_V"
  cd "$S/libogg-$OGG_V"
  ./configure --prefix="$P" --disable-shared --enable-static
  make -j"$JOBS" install
}
b_vorbis() {
  tarball "https://downloads.xiph.org/releases/vorbis/libvorbis-$VORBIS_V.tar.gz" "libvorbis-$VORBIS_V"
  cd "$S/libvorbis-$VORBIS_V"
  sed -i '' 's/-force_cpusubtype_ALL//g' configure
  ./configure --prefix="$P" --disable-shared --enable-static --disable-oggtest --disable-examples --disable-docs
  make -j"$JOBS" install
}
b_opus() {
  tarball "https://downloads.xiph.org/releases/opus/opus-$OPUS_V.tar.gz" "opus-$OPUS_V"
  cd "$S/opus-$OPUS_V"
  ./configure --prefix="$P" --disable-shared --enable-static --disable-doc --disable-extra-programs
  make -j"$JOBS" install
}
b_x264() {
  [ -d "$S/x264" ] || { git clone -q --branch stable https://code.videolan.org/videolan/x264.git "$S/x264"; git -C "$S/x264" -c advice.detachedHead=false checkout -q "$X264_COMMIT"; }
  cd "$S/x264"
  ./configure --prefix="$P" --enable-static --enable-pic --disable-cli
  make -j"$JOBS" install
}
b_vpx() {
  clone https://github.com/webmproject/libvpx.git "$VPX_V" libvpx
  cd "$S/libvpx"
  ./configure --prefix="$P" --target=arm64-darwin22-gcc --disable-shared --enable-static --enable-pic --enable-vp9 --enable-vp8 \
    --disable-examples --disable-tools --disable-docs --disable-unit-tests
  make -j"$JOBS" install
}
b_freetype() {
  clone https://github.com/freetype/freetype.git "$FREETYPE_V" freetype
  cd "$S/freetype"; rm -rf _b
  meson setup _b --prefix="$P" --libdir=lib --buildtype=release --default-library=static \
    -Dzlib=disabled -Dbzip2=disabled -Dpng=disabled -Dbrotli=disabled -Dharfbuzz=disabled
  ninja -C _b install
}
b_fribidi() {
  clone https://github.com/fribidi/fribidi.git "$FRIBIDI_V" fribidi
  cd "$S/fribidi"; rm -rf _b
  meson setup _b --prefix="$P" --libdir=lib --buildtype=release --default-library=static -Ddocs=false -Dbin=false -Dtests=false
  ninja -C _b install
}
b_harfbuzz() {
  clone https://github.com/harfbuzz/harfbuzz.git "$HARFBUZZ_V" harfbuzz
  cd "$S/harfbuzz"; rm -rf _b
  meson setup _b --prefix="$P" --libdir=lib --buildtype=release --default-library=static \
    -Dfreetype=enabled -Dglib=disabled -Dgobject=disabled -Dcairo=disabled -Dicu=disabled -Dtests=disabled -Ddocs=disabled -Dutilities=disabled
  ninja -C _b install
}
b_libass() {
  tarball "https://github.com/libass/libass/releases/download/$LIBASS_V/libass-$LIBASS_V.tar.xz" "libass-$LIBASS_V"
  cd "$S/libass-$LIBASS_V"
  ./configure --prefix="$P" --disable-shared --enable-static --disable-fontconfig --enable-coretext --disable-require-system-font-provider
  make -j"$JOBS" install
}
b_whisper() {
  clone https://github.com/ggml-org/whisper.cpp.git "$WHISPER_V" whisper.cpp
  cd "$S/whisper.cpp"; rm -rf _b
  cmake -S . -B _b -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$P" -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_OSX_ARCHITECTURES=arm64 \
    -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=OFF -DWHISPER_COREML=OFF \
    -DGGML_METAL=OFF -DGGML_BLAS=OFF -DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16
  cmake --build _b -j"$JOBS"
  cmake --install _b
  cat > "$P/lib/pkgconfig/whisper.pc" <<PC
prefix=$P
Name: whisper
Description: whisper.cpp
Version: ${WHISPER_V#v}
Cflags: -I$P/include
Libs: -L$P/lib -lwhisper -lggml -lggml-cpu -lggml-base -lc++ -framework Accelerate -framework Foundation
PC
}
b_ffmpeg() {
  tarball "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_V.tar.xz" "ffmpeg-$FFMPEG_V"
  cd "$S/ffmpeg-$FFMPEG_V"
  ./configure --prefix="$P" --pkg-config="$PKG_CONFIG" --pkg-config-flags=--static \
    --extra-cflags="$CFLAGS" --extra-ldflags="$LDFLAGS" --extra-libs="-lc++" \
    --enable-gpl --enable-version3 --enable-static --disable-shared --disable-doc --disable-ffplay --disable-network \
    --enable-libx264 --enable-libmp3lame --enable-libopus --enable-libvorbis --enable-libvpx \
    --enable-libass --enable-libfreetype --enable-libfribidi --enable-libharfbuzz --enable-whisper \
    --enable-videotoolbox --enable-audiotoolbox
  make -j"$JOBS"
  make install
}

for lib in lame ogg vorbis opus x264 vpx freetype fribidi harfbuzz libass whisper ffmpeg; do step "$lib" "b_$lib"; done

mkdir -p "$HERE/bin"
cp "$P/bin/ffmpeg" "$P/bin/ffprobe" "$HERE/bin/"
strip "$HERE/bin/ffmpeg" "$HERE/bin/ffprobe"
codesign --force --sign - "$HERE/bin/ffmpeg" "$HERE/bin/ffprobe"
echo "--- bibliotecas externas do ffmpeg:"
otool -L "$HERE/bin/ffmpeg" | grep -v -E '/System/Library|/usr/lib/' || echo "nenhuma"
"$HERE/bin/ffmpeg" -hide_banner -version | head -1
"$HERE/bin/ffmpeg" -hide_banner -filters | grep -E ' (whisper|ass|subtitles) '
ls -lh "$HERE/bin"
echo "PRONTO"
