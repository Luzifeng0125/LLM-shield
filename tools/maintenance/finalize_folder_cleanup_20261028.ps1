$ErrorActionPreference='Stop'
$project=[IO.Path]::GetFullPath('D:\challenge_AI\LLM-Shield')
$visualRoot=[IO.Path]::GetFullPath('C:\Users\nicholas\.codex\visualizations\2026\10\26\01a176d0-0c9a-77c3-a5f9-8127b00c6443')
$auditPath=Join-Path $project '04_技术文档\整理记录\目录整理审计_20261028.json'
$audit=Get-Content -LiteralPath $auditPath -Raw -Encoding utf8 | ConvertFrom-Json
$extraDeleted=[Collections.Generic.List[object]]::new()
function Check-Within([string]$path,[string]$root) {
    $full=[IO.Path]::GetFullPath($path)
    if (-not $full.StartsWith($root.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { throw "Outside approved directory: $full" }
    return $full
}
$snapshot=Check-Within (Join-Path $visualRoot 'source-review-81294fd') $visualRoot
if (Test-Path -LiteralPath $snapshot) {
    if ((Get-Item -LiteralPath $snapshot).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unexpected snapshot link' }
    $snapshotFiles=@(Get-ChildItem -LiteralPath $snapshot -File -Recurse -Force)
    if ($snapshotFiles.Count -ne 99 -or ($snapshotFiles | Measure-Object Length -Sum).Sum -ne 960840) { throw 'Snapshot changed since comparison; refusing removal' }
    & git -C $project cat-file -e '81294fd50a1b4b1b5d392a8f171664450fc80461'
    if ($LASTEXITCODE -ne 0) { throw 'Original Git baseline no longer available' }
    foreach ($file in $snapshotFiles) {
        $extraDeleted.Add([pscustomobject]@{path=$file.FullName;bytes=$file.Length;reason='read_only_snapshot_verified_equal_to_preserved_git_baseline'})
    }
    Remove-Item -LiteralPath $snapshot -Recurse -Force
}
$reviewZip=Check-Within (Join-Path $project '03_数据与人工复核\任务必要性复核_20261026_v2.zip') $project
if (Test-Path -LiteralPath $reviewZip) {
    $extraDeleted.Add([pscustomobject]@{path=$reviewZip;bytes=(Get-Item -LiteralPath $reviewZip).Length;sha256=(Get-FileHash -LiteralPath $reviewZip).Hash;reason='all_6_zip_entries_verified_equal_to_retained_files_before_path_updates'})
    Remove-Item -LiteralPath $reviewZip
}
$planNames=@('隐盾优化方案-01总方案.md','隐盾优化方案-02人工执行手册.md','隐盾优化方案-03AI任务书.md')
$newPlanFiles=@($planNames | ForEach-Object {Join-Path $project ('01_优化方案\'+$_)})
$newZip=Check-Within (Join-Path $project '01_优化方案\隐盾优化详细方案_20261028.zip') $project
if (Test-Path -LiteralPath $newZip) { throw 'New plan archive exists; refusing overwrite' }
Compress-Archive -LiteralPath $newPlanFiles -DestinationPath $newZip -CompressionLevel Optimal
$archive=[IO.Compression.ZipFile]::OpenRead($newZip)
try {
    if ($archive.Entries.Count -ne 3) { throw 'Wrong plan archive entries' }
    foreach($entry in $archive.Entries) {
        if ($planNames -notcontains $entry.FullName) { throw 'Unexpected archive member' }
        $stream=$entry.Open()
        $hasher=[Security.Cryptography.SHA256]::Create()
        try {$packed=[BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-','')}
        finally {$stream.Dispose();$hasher.Dispose()}
        $source=Join-Path $project ('01_优化方案\'+$entry.FullName)
        if ($packed -ne (Get-FileHash -LiteralPath $source).Hash) { throw 'Plan archive hash mismatch' }
    }
} finally {$archive.Dispose()}
$oldZip=Check-Within (Join-Path $visualRoot '隐盾优化详细方案_20261027.zip') $visualRoot
if(Test-Path -LiteralPath $oldZip) {
    $extraDeleted.Add([pscustomobject]@{path=$oldZip;bytes=(Get-Item -LiteralPath $oldZip).Length;reason='superseded_by_verified_archive_with_current_paths'})
    Remove-Item -LiteralPath $oldZip
}
foreach($name in $planNames) {
    $pointer=Check-Within (Join-Path $visualRoot $name) $visualRoot
    $destination=(Join-Path $project ('01_优化方案\'+$name)).Replace('\','/')
    $text=@('# 文件已归入 LLM-Shield','','2026-10-28 已整理到统一项目目录。','',"[打开当前文档](<$destination>)",'') -join [Environment]::NewLine
    [IO.File]::WriteAllText($pointer,$text,[Text.UTF8Encoding]::new($false))
}
$audit.deleted=@($audit.deleted)+@($extraDeleted)
$audit.git='relocated_with_branch_and_history_verified'
$audit | Add-Member -NotePropertyName 'cleanup_totals' -NotePropertyValue ([pscustomobject]@{
    files=$audit.deleted.Count
    bytes=($audit.deleted | Measure-Object bytes -Sum).Sum
    review_zip_entries_verified=6
    snapshot_files_verified=99
    plan_archive_hashes='passed'
}) -Force
$audit | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $auditPath -Encoding utf8
$maintenance=Join-Path $project 'tools\maintenance'
[IO.Directory]::CreateDirectory($maintenance) | Out-Null
foreach($name in @('reorganize_workspace_20261028.ps1','finish_reorganization_20261028.py')) {
    $source=[IO.Path]::GetFullPath('D:\challenge_AI\'+$name)
    $target=Check-Within (Join-Path $maintenance $name) $project
    if(Test-Path -LiteralPath $target) { throw "Maintenance target exists: $target" }
    Move-Item -LiteralPath $source -Destination $target
}
$audit.cleanup_totals | ConvertTo-Json
