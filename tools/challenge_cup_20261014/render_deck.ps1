param([Parameter(Mandatory=$true)][string]$InputDeck, [Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$deckPath = (Resolve-Path -LiteralPath $InputDeck).Path
$renderFolder = [IO.Path]::GetFullPath($OutputDirectory)
if (-not $renderFolder.StartsWith('D:\challenge_AI\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Output must remain in workspace' }
New-Item -ItemType Directory -Force -Path $renderFolder | Out-Null
$powerPointApp = $null
$openDeck = $null
try {
    $powerPointApp = New-Object -ComObject PowerPoint.Application
    $openDeck = $powerPointApp.Presentations.Open($deckPath, -1, 0, 0)
    for ($slideNumber = 1; $slideNumber -le $openDeck.Slides.Count; $slideNumber++) {
        $slideOutput = Join-Path $renderFolder ('slide-{0:D2}.png' -f $slideNumber)
        $openDeck.Slides.Item($slideNumber).Export($slideOutput, 'PNG', 1600, 900)
    }
    Write-Output "Rendered $($openDeck.Slides.Count) slides"
} finally {
    if ($null -ne $openDeck) { $openDeck.Close(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($openDeck) }
    if ($null -ne $powerPointApp) { $powerPointApp.Quit(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($powerPointApp) }
}
