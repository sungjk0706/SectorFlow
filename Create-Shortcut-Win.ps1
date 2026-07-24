# Windows용 SectorFlow 바로가기 + 아이콘 생성 스크립트
# PowerShell에서 실행 (우클릭 → PowerShell로 실행)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$IcoPath = Join-Path $Root "assets\icons\SectorFlow-Win.ico"
$CommandFile = Join-Path $Root "SectorFlow.command"
$ShortcutPath = Join-Path $Root "SectorFlow-Win.lnk"

Write-Host "============================================"
Write-Host "  SectorFlow 윈도우 바로가기 생성"
Write-Host "============================================"
Write-Host ""

if (-not (Test-Path $IcoPath)) {
    Write-Host "아이콘 파일을 찾을 수 없습니다: $IcoPath"
    exit 1
}

if (-not (Test-Path $CommandFile)) {
    Write-Host "SectorFlow.command 파일을 찾을 수 없습니다: $CommandFile"
    exit 1
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)

# 실행은 Git Bash 또는 WSL을 통해 SectorFlow.command 를 실행
# 아래 경로는 Git Bash 기본 설치 경로입니다. 다른 경로면 수정하세요.
$GitBash = "C:\Program Files\Git\git-bash.exe"
if (Test-Path $GitBash) {
    $Shortcut.TargetPath = $GitBash
    $Shortcut.Arguments = "--cd=`"$Root`" -c './SectorFlow.command'"
} else {
    # WSL이 설치되어 있다면 wsl 사용
    $Shortcut.TargetPath = "wsl.exe"
    $Shortcut.Arguments = "bash -c 'cd ""$Root"" && ./SectorFlow.command'"
}

$Shortcut.IconLocation = $IcoPath
$Shortcut.Save()

Write-Host "바로가기가 생성되었습니다: $ShortcutPath"
Write-Host "아이콘이 파도 모양으로 적용되었습니다."
Write-Host ""
Write-Host "참고: 이 바로가기는 Git Bash 또는 WSL이 설치된 환경에서만 실행됩니다."
Write-Host "Git Bash가 없다면 https://git-scm.com/download/win 에서 설치해 주세요."
