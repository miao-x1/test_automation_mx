# ================================================================== #
#  本地开发一键启动脚本                                                #
#                                                                    #
#  用途: 启动 Docker 数据库 + 前端 Dev Server                          #
#        后端请在 PyCharm 中运行 (app.main:app) 以便断点调试           #
#                                                                    #
#  使用: 右键 → 用 PowerShell 运行，或在终端中执行:                     #
#        powershell -ExecutionPolicy Bypass -File dev-start.ps1       #
# ================================================================== #

param(
    [switch]$DockerOnly,
    [switch]$FrontendOnly,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"

# ===== 停止所有服务 =====
if ($Stop) {
    Write-Host "`n[1/3] 停止前端 Dev Server..." -ForegroundColor Yellow
    Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "vite"
    } | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "  前端已停止" -ForegroundColor Green

    Write-Host "[2/3] 停止 Docker 数据库..." -ForegroundColor Yellow
    docker compose -f docker-compose.dev.yml down
    Write-Host "  Docker 数据库已停止" -ForegroundColor Green

    Write-Host "[3/3] 提示: 后端请在 PyCharm 中点击停止按钮`n" -ForegroundColor Cyan
    return
}

# ===== 启动 Docker 数据库 =====
if (-not $FrontendOnly) {
    Write-Host "`n[1/2] 启动 Docker 数据库 (MySQL/Redis/Milvus/Neo4j)..." -ForegroundColor Cyan
    docker compose -f docker-compose.dev.yml up -d

    Write-Host "`n  等待数据库健康检查..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5

    $containers = docker ps --format "{{.Names}} {{.Status}}" 2>$null
    Write-Host "`n  容器状态:" -ForegroundColor Gray
    Write-Host $containers

    Write-Host "`n  数据库端口映射:" -ForegroundColor Gray
    Write-Host "  MySQL  -> localhost:3307"
    Write-Host "  Redis  -> localhost:6379"
    Write-Host "  Milvus -> localhost:19530"
    Write-Host "  Neo4j  -> localhost:7474 / 7687"
    Write-Host "`n  Docker 数据库启动完成" -ForegroundColor Green
}

if ($DockerOnly) {
    Write-Host "`n提示: 后端请在 PyCharm 中运行 (app.main:app)`n" -ForegroundColor Cyan
    Write-Host "提示: 前端请在 frontend 目录运行 npm run dev`n" -ForegroundColor Cyan
    return
}

# ===== 启动前端 Dev Server =====
Write-Host "`n[2/2] 启动前端 Dev Server (Vite :3000)..." -ForegroundColor Cyan

$frontendDir = Join-Path $PSScriptRoot "frontend"
if (-not (Test-Path $frontendDir)) {
    Write-Host "  错误: frontend 目录不存在" -ForegroundColor Red
    return
}

# 检查 node_modules
$nodeModules = Join-Path $frontendDir "node_modules"
if (-not (Test-Path $nodeModules)) {
    Write-Host "  node_modules 不存在，正在安装依赖..." -ForegroundColor Yellow
    Push-Location $frontendDir
    npm install
    Pop-Location
}

# 后台启动 Vite
Push-Location $frontendDir
Start-Process -FilePath "cmd" -ArgumentList "/c npm run dev" -WindowStyle Normal
Pop-Location

Write-Host "`n  前端启动中: http://localhost:3000" -ForegroundColor Green

Write-Host "`n================================================" -ForegroundColor Cyan
Write-Host "  全部就绪!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  后端:  在 PyCharm 中运行 app.main:app"
Write-Host "          → http://localhost:8000 (API 文档: /docs)"
Write-Host "  前端:  http://localhost:3000"
Write-Host "  数据库: Docker 容器中运行"
Write-Host ""
Write-Host "  停止所有服务: .\dev-start.ps1 -Stop"
Write-Host "================================================`n" -ForegroundColor Cyan
