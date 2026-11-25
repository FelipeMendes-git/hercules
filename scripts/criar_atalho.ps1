# Cria um atalho do Hércules na Área de Trabalho (e no menu Iniciar).
$raiz = Split-Path $PSScriptRoot -Parent
$exe = Join-Path $raiz ".venv\Scripts\hercules.exe"
if (-not (Test-Path $exe)) {
    Write-Host "O ambiente ainda não foi instalado. Rode scripts\instalar.ps1 primeiro."
    exit 1
}
$icone = Join-Path $raiz "recursos\icone.ico"
if (-not (Test-Path $icone)) {
    & (Join-Path $raiz ".venv\Scripts\python.exe") (Join-Path $raiz "scripts\gerar_icone.py") | Out-Null
}
$shell = New-Object -ComObject WScript.Shell
$destinos = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs")
)
foreach ($pasta in $destinos) {
    $atalho = $shell.CreateShortcut((Join-Path $pasta "Hércules.lnk"))
    $atalho.TargetPath = $exe
    $atalho.WorkingDirectory = $raiz
    $atalho.Description = "Hércules: assistente de voz para o Claude Code"
    if (Test-Path $icone) { $atalho.IconLocation = $icone }
    $atalho.Save()
    Write-Host "Atalho criado em $pasta"
}
