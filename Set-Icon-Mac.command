#!/bin/bash
cd "$(dirname "$0")"

ICONS_DIR="assets/icons"
ICON_FILE="$ICONS_DIR/SectorFlow-Mac.icns"
TARGET_FILE="SectorFlow.command"

echo "============================================"
echo "  SectorFlow 맥 아이콘 적용"
echo "============================================"
echo ""

if [ ! -f "$ICON_FILE" ]; then
    echo "아이콘 파일을 찾을 수 없습니다: $ICON_FILE"
    exit 1
fi

if [ ! -f "$TARGET_FILE" ]; then
    echo "대상 파일을 찾을 수 없습니다: $TARGET_FILE"
    exit 1
fi

if command -v fileicon >/dev/null 2>&1; then
    fileicon set "$TARGET_FILE" "$ICON_FILE"
    echo "아이콘이 적용되었습니다."
else
    echo "fileicon 명령어가 설치되어 있지 않습니다."
    echo ""
    echo "수동으로 적용하려면:"
    echo "1. Finder에서 $TARGET_FILE 을(를) 선택하고 우클릭"
    echo "2. '정보 가져오기(Get Info)' 선택"
    echo "3. $ICON_FILE 을(를) 복사(Command+C)"
    echo "4. '정보 가져오기' 창 왼쪽 위의 작은 아이콘을 클릭 후 붙여넣기(Command+V)"
    echo ""
    echo "fileicon 자동 설치 (Homebrew 필요):"
    echo "  brew install fileicon"
fi

echo ""
echo "완료. Finder에서 아이콘이 파도 모양으로 바뀌었는지 확인해 보세요."
