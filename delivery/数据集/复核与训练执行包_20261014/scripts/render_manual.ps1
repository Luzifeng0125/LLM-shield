$ErrorActionPreference = 'Stop'
$manualRoot = Split-Path -Parent $PSScriptRoot
$manualDocx = Join-Path $manualRoot '隐盾数据复核与模型训练执行方案.docx'
$manualQa = Join-Path $manualRoot 'qa\document'
New-Item -ItemType Directory -Force -Path $manualQa | Out-Null
$manualPdf = Join-Path $manualQa 'manual.pdf'
$manualWord = $null
$manualOpen = $null
try {
    $manualWord = New-Object -ComObject Word.Application
    $manualWord.Visible = $false
    $manualWord.DisplayAlerts = 0
    $manualOpen = $manualWord.Documents.Open($manualDocx, $false, $true)
    $manualOpen.Repaginate()
    $manualOpen.ExportAsFixedFormat($manualPdf, 17)
    Write-Output "Manual pages: $($manualOpen.ComputeStatistics(2))"
} finally {
    if ($null -ne $manualOpen) {
        $manualOpen.Close(0)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($manualOpen)
    }
    if ($null -ne $manualWord) {
        $manualWord.Quit()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($manualWord)
    }
}
& 'C:\Users\nicholas\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe' -scale-to 1600 -png $manualPdf (Join-Path $manualQa 'page')
if ($LASTEXITCODE -ne 0) { throw 'Page rendering failed' }
