# Instala o Hércules nesta pasta: ambiente Python, dependências, pasta de dados e atalho.
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host "Instale o Python 3.12 (python.org) marcando 'Add Python to PATH' e rode de novo."
    exit 1
}
if (-not (Test-Path ".venv")) {
    Write-Host "Criando o ambiente Python..."
    py -3.12 -m venv .venv
}
Write-Host "Instalando as dependências (alguns minutos na primeira vez)..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# Modo portátil: configuração, modelos e conversas ficam em .\dados
New-Item -ItemType Directory -Force "dados" | Out-Null

& (Join-Path $PSScriptRoot "criar_atalho.ps1")

Write-Host ""
Write-Host "Pronto."
Write-Host "- Placa NVIDIA sem CUDA reaproveitável? Rode:  .venv\Scripts\python -m pip install -e "".[gpu]"""
Write-Host "- Se ainda não entrou no Claude Code, rode:  claude auth login --claudeai"
Write-Host "- Os modelos de voz e reconhecimento são baixados na primeira vez que o app abrir."
