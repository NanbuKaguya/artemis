# Artemis 一键落地（Windows PowerShell）
#
# 用法（在仓库目录下）：
#   powershell -ExecutionPolicy Bypass -File bootstrap.ps1
#
# 设计与 bootstrap.sh 一致：不需要管理员权限、幂等、停在第一个真问题上。

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Say  { param($m) Write-Host $m }
function Step { param($m) Write-Host "`n==> $m" -ForegroundColor White }
function OK   { param($m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn { param($m) Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Die  { param($m, $hint)
    Write-Host "`n  [X] $m`n" -ForegroundColor Red
    if ($hint) { Write-Host "  $hint`n" }
    exit 1
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
Set-Location $Root

Say "Artemis 一键落地"
Say "目录: $Root"

# ---------------------------------------------------------------- 1. Python
Step "1/6 检查 Python"
$Py = $null
# Windows 上优先用 py launcher，它能精确选版本
foreach ($cand in @("py -3.13", "py -3.12", "py -3.11", "python", "python3")) {
    $parts = $cand -split ' '
    $exe = $parts[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $args = if ($parts.Count -gt 1) { $parts[1..($parts.Count-1)] } else { @() }
    try {
        $check = & $exe @args -c "import sys; print(1 if sys.version_info>=(3,11) else 0)" 2>$null
        if ($check -eq "1") { $Py = $cand; break }
    } catch { continue }
}
if (-not $Py) {
    Die "找不到 Python 3.11+" @"
从 https://www.python.org/downloads/ 安装 Python 3.12
安装时务必勾选 "Add Python to PATH"
"@
}
$pyParts = $Py -split ' '
$pyExe = $pyParts[0]
$pyArgs = if ($pyParts.Count -gt 1) { $pyParts[1..($pyParts.Count-1)] } else { @() }
$ver = & $pyExe @pyArgs --version
OK "$ver ($Py)"

# ---------------------------------------------------------------- 2. venv
Step "2/6 创建虚拟环境"
if (Test-Path $Venv) {
    OK "已存在，复用 .venv"
} else {
    & $pyExe @pyArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Die "创建虚拟环境失败" }
    OK "已创建 .venv"
}
$VPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VPy)) { Die "虚拟环境不完整：$VPy 不存在" }

# ---------------------------------------------------------------- 3. 依赖
Step "3/6 安装依赖（首次约 2-4 分钟）"
& $VPy -m pip install --quiet --upgrade pip 2>$null
$pipLog = Join-Path $env:TEMP "artemis_pip.log"
& $VPy -m pip install --quiet -e "$Root[data]" 2>$pipLog
if ($LASTEXITCODE -eq 0) {
    OK "核心依赖 + AkShare 安装完成"
} else {
    Warn "带 AkShare 的安装失败，退回只装核心依赖"
    & $VPy -m pip install --quiet -e $Root 2>$null
    if ($LASTEXITCODE -ne 0) {
        Die "核心依赖也装不上" @"
看完整日志：type $pipLog
国内网络慢可以换源：
  $VPy -m pip install -e "$Root[data]" -i https://pypi.tuna.tsinghua.edu.cn/simple
"@
    }
    OK "核心依赖已装（AkShare 缺失，排雷功能不可用）"
}

# 验证真的能导入，而不是相信 pip 的退出码
& $VPy -c "import artemis.lite, artemis.service, artemis.doctor" 2>$null
if ($LASTEXITCODE -ne 0) {
    Die "包装上了但导入失败" "请把这条命令的输出发给我：`n    $VPy -c `"import artemis.lite`""
}
OK "模块导入验证通过"

# ---------------------------------------------------------------- 4. 自检
Step "4/6 环境体检"
& $VPy -m artemis.doctor
$DoctorRc = $LASTEXITCODE

# ---------------------------------------------------------------- 5. 交易日历
Step "5/6 交易日历"
if ($DoctorRc -eq 0) {
    $out = & $VPy -m artemis.service calendar-refresh 2>$null
    if ($out -match '"ok": true') {
        OK "已刷新（没有它，节假日会被当成交易日）"
    } else {
        Warn "刷新失败 —— 多半是连不上数据源，见上面体检结果"
    }
} else {
    Warn "体检有阻塞项，跳过日历刷新。修完后手动跑："
    Say  "  $VPy -m artemis.service calendar-refresh"
}

# ---------------------------------------------------------------- 6. 自选股
Step "6/6 自选股清单"
$WL = Join-Path $Root "watchlist.txt"
$hasCodes = $false
if (Test-Path $WL) {
    $lines = Get-Content $WL | Where-Object { $_.Trim() -and -not $_.TrimStart().StartsWith("#") }
    if ($lines.Count -gt 0) { $hasCodes = $true; OK "已有 $($lines.Count) 只" }
}
if (-not $hasCodes) {
    @"
# 每行一个 6 位股票代码，# 开头为注释
# 删掉下面的示例，换成你自己的持仓和候选
600519
000001
"@ | Set-Content -Path $WL -Encoding UTF8
    OK "已创建模板 watchlist.txt（含 2 只示例，请替换）"
}

# ---------------------------------------------------------------- 收尾
$Act = Join-Path $Venv "Scripts\Activate.ps1"
Say ""
Say "────────────────────────────────────────────────────"
if ($DoctorRc -eq 0) {
    Write-Host "安装完成。" -ForegroundColor Green
    Say ""
    Say "接下来（每次开新终端都要先激活环境）："
    Say ""
    Say "  $Act"
    Say ""
    Say "  1. 编辑 watchlist.txt，填上你的自选股"
    Say "  2. artemis watch      <- 每天开盘前跑，标 X 的今天不碰"
    Say "  3. artemis log        <- 每次下单前跑，写下理由和失效条件"
    Say "  4. artemis review     <- 每周跑，看临时起意占比"
    Say ""
    Say "就这四步。不需要 Hermes、计划任务、Level-2、财务数据。"
} else {
    Write-Host "安装完成，但体检有阻塞项。" -ForegroundColor Yellow
    Say ""
    Say "按上面「下一步」的提示修复，然后重跑："
    Say ""
    Say "  powershell -ExecutionPolicy Bypass -File bootstrap.ps1"
    Say ""
    Say "脚本是幂等的，重复跑不会有副作用。"
}
Say "────────────────────────────────────────────────────"
