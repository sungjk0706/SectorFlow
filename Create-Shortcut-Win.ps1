# Windows용 SectorFlow 바로가기 + 아이콘 생성 스크립트
# PowerShell에서 실행 (우클릭 → PowerShell로 실행)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$IcoPath = Join-Path $Root "assets\icons\SectorFlow-Win.ico"
$TargetFile = Join-Path $Root "SectorFlow-Win.bat"
$ShortcutPath = Join-Path $Root "SectorFlow-Win.lnk"

Write-Host "============================================"
Write-Host "  SectorFlow 윈도우 바로가기 생성"
Write-Host "============================================"
Write-Host ""

if (-not (Test-Path $IcoPath)) {
    Write-Host "아이콘 파일을 찾을 수 없습니다: $IcoPath"
    exit 1
}

if (-not (Test-Path $TargetFile)) {
    Write-Host "런처 파일을 찾을 수 없습니다: $TargetFile"
    exit 1
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)

# SectorFlow-Win.bat 를 직접 실행 (Git Bash 불필요)
$Shortcut.TargetPath = $TargetFile
$Shortcut.WorkingDirectory = $Root
$Shortcut.IconLocation = $IcoPath
$Shortcut.WindowStyle = 1
$Shortcut.Save()

Write-Host "바로가기가 생성되었습니다: $ShortcutPath"
Write-Host "아이콘이 적용되었습니다."
Write-Host ""
Write-Host "사용법: SectorFlow-Win.lnk 더블클릭으로 실행"
