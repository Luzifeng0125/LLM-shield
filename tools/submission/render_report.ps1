$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$submissionDoc = Join-Path $repositoryRoot '隐盾提交材料_20261014\隐盾项目最终报告_本地模型方案版.docx'
$submissionPdf = Join-Path $repositoryRoot '隐盾提交材料_20261014\隐盾项目最终报告_本地模型方案版.pdf'
New-Item -ItemType Directory -Force -Path (Split-Path $submissionPdf) | Out-Null
$submissionWord = $null
$submissionOpenDoc = $null
try {
    $submissionWord = New-Object -ComObject Word.Application
    $submissionWord.Visible = $false
    $submissionWord.DisplayAlerts = 0
    $submissionOpenDoc = $submissionWord.Documents.Open($submissionDoc, $false, $true)
    $submissionOpenDoc.Repaginate()
    $submissionOpenDoc.ExportAsFixedFormat($submissionPdf, 17)
    Write-Output "Report pages: $($submissionOpenDoc.ComputeStatistics(2))"
} finally {
    if ($null -ne $submissionOpenDoc) {
        $submissionOpenDoc.Close(0)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($submissionOpenDoc)
    }
    if ($null -ne $submissionWord) {
        $submissionWord.Quit()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($submissionWord)
    }
}
