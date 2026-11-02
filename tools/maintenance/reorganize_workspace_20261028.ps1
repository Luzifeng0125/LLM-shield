$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath('D:\challenge_AI')
$project = [IO.Path]::GetFullPath('D:\challenge_AI\LLM-Shield')
$plansRoot = [IO.Path]::GetFullPath('C:\Users\nicholas\.codex\visualizations\2026\10\26\01a176d0-0c9a-77c3-a5f9-8127b00c6443')
if (Test-Path -LiteralPath $project) { throw 'Target project already exists; refusing to merge or overwrite.' }
function Assert-Child([string]$path, [string]$parent) {
    $absolute = [IO.Path]::GetFullPath($path)
    if (-not $absolute.StartsWith($parent.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside the intended root: $absolute"
    }
    return $absolute
}
function Move-Checked([string]$source, [string]$target) {
    $source = Assert-Child $source $workspace
    $target = Assert-Child $target $project
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing source: $source" }
    if (Test-Path -LiteralPath $target) { throw "Target collision: $target" }
    if ((Get-Item -LiteralPath $source -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing to relocate a reparse point: $source"
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
    Move-Item -LiteralPath $source -Destination $target
    $script:moves.Add([pscustomobject]@{from=$source;to=$target})
}
$moves = [Collections.Generic.List[object]]::new()
$deleted = [Collections.Generic.List[object]]::new()
$protected = [Collections.Generic.List[object]]::new()
$cachePaths = @(Get-ChildItem -LiteralPath (Join-Path $workspace 'delivery') -Directory -Recurse -Force |
    Where-Object {$_.Name -in @('__pycache__','.pytest_cache','.mypy_cache','.ruff_cache') -or $_.Name -like 'pytest-cache-files-*'} |
    Sort-Object {$_.FullName.Length})
$cacheRoots = [Collections.Generic.List[string]]::new()
foreach ($cache in $cachePaths) {
    $full = Assert-Child $cache.FullName (Join-Path $workspace 'delivery')
    if ($cache.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Unexpected cache link: $full" }
    if (-not ($cacheRoots | Where-Object {$full.StartsWith($_+'\',[StringComparison]::OrdinalIgnoreCase)})) {
        $cacheRoots.Add($full)
    }
}
$protectRoots = @('delivery\app\models','delivery\app\data','delivery\数据集','delivery\提交材料','delivery\runtime\base_models')
foreach ($relative in $protectRoots) {
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $workspace $relative) -File -Recurse -Force) {
        if ($file.FullName -match '\\__pycache__\\|\\\.pytest_cache\\') { continue }
        $protected.Add([pscustomobject]@{old_path=$file.FullName;bytes=$file.Length;sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash})
    }
}
$envFile = Join-Path $workspace 'delivery\app\.env'
if (Test-Path -LiteralPath $envFile) {
    $protected.Add([pscustomobject]@{old_path=$envFile;bytes=(Get-Item -LiteralPath $envFile).Length;sha256=(Get-FileHash -LiteralPath $envFile -Algorithm SHA256).Hash})
}
[IO.Directory]::CreateDirectory($project) | Out-Null
foreach ($pair in @(
    @('delivery','delivery'),
    @('docs','04_技术文档'),
    @('tools','tools'),
    @('README.md','04_技术文档\项目原说明.md'),
    @('AI_EXECUTION_PLAN.md','AI_EXECUTION_PLAN.md'),
    @('启动隐盾.cmd','启动隐盾.cmd'),
    @('.gitignore','.gitignore'),
    @('.gitattributes','.gitattributes')
)) {
    Move-Checked (Join-Path $workspace $pair[0]) (Join-Path $project $pair[1])
}
Move-Checked (Join-Path $project 'delivery\数据集') (Join-Path $project '03_数据与人工复核')
Move-Checked (Join-Path $project 'delivery\提交材料') (Join-Path $project '02_提交材料')
$submissions = Join-Path $project '02_提交材料'
Move-Checked (Join-Path $submissions '隐盾项目申报书.docx') (Join-Path $submissions '01_申报书\隐盾项目申报书.docx')
Move-Checked (Join-Path $submissions '隐盾项目最终报告_本地模型方案版_更新20261016.docx') (Join-Path $submissions '02_报告\隐盾项目最终报告_本地模型方案版_更新20261016.docx')
Move-Checked (Join-Path $submissions '隐盾-隐私保护对话系统-苹果风优化版.pptx') (Join-Path $submissions '99_历史版本\隐盾-隐私保护对话系统-苹果风优化版.pptx')
$revision = Join-Path $submissions '20261017_报告核对与PPT修订'
Move-Checked (Join-Path $revision '隐盾-隐私保护对话系统-苹果风-20261017内容修订.pptx') (Join-Path $submissions '03_答辩PPT\隐盾-隐私保护对话系统-苹果风-20261017内容修订.pptx')
Move-Checked (Join-Path $revision '计划书更改建议.md') (Join-Path $submissions '02_报告\计划书更改建议_20261017.md')
Move-Checked $revision (Join-Path $submissions '99_历史版本\20261017_制作过程')
$newPlans = Join-Path $project '01_优化方案'
[IO.Directory]::CreateDirectory($newPlans) | Out-Null
foreach ($name in @('隐盾优化方案-01总方案.md','隐盾优化方案-02人工执行手册.md','隐盾优化方案-03AI任务书.md')) {
    $source = Assert-Child (Join-Path $plansRoot $name) $plansRoot
    $target = Assert-Child (Join-Path $newPlans $name) $project
    Copy-Item -LiteralPath $source -Destination $target
    if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $target).Hash) { throw "Plan copy mismatch: $name" }
    $moves.Add([pscustomobject]@{from=$source;to=$target;operation='copy_pending_link_redirect'})
}
# Only disposable cache directories and reproducible render intermediates are removed.
foreach ($oldCache in $cacheRoots) {
    $mappedCache = $oldCache
    foreach ($move in $moves) {
        if ($mappedCache.StartsWith($move.from.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) {
            $mappedCache = $move.to + $mappedCache.Substring($move.from.Length)
        }
    }
    $cache = Assert-Child $mappedCache $project
    if (-not (Test-Path -LiteralPath $cache)) { throw "Cache unexpectedly missing: $cache" }
    foreach ($file in Get-ChildItem -LiteralPath $cache -File -Recurse -Force) {
        $deleted.Add([pscustomobject]@{path=$file.FullName;bytes=$file.Length;reason='rebuildable_python_or_test_cache'})
    }
    Remove-Item -LiteralPath $cache -Recurse -Force
}
$render = Assert-Child (Join-Path $submissions '99_历史版本\20261017_制作过程\build\source_render') $project
if (Test-Path -LiteralPath $render) {
    foreach ($file in Get-ChildItem -LiteralPath $render -File -Recurse -Force) {
        if ($file.Extension -notin @('.png','.json')) { throw "Unknown file in render cache: $($file.Name)" }
        $deleted.Add([pscustomobject]@{path=$file.FullName;bytes=$file.Length;reason='rebuildable_slide_render_source_deck_preserved'})
    }
    Remove-Item -LiteralPath $render -Recurse -Force
}
$emptyProduct = Assert-Child (Join-Path $submissions '99_历史版本\20261017_制作过程\成品') $project
if ((Test-Path -LiteralPath $emptyProduct) -and -not (Get-ChildItem -LiteralPath $emptyProduct -Force)) {
    Remove-Item -LiteralPath $emptyProduct
}
$recordDir=Join-Path $project '04_技术文档\整理记录'
[IO.Directory]::CreateDirectory($recordDir) | Out-Null
$audit = [ordered]@{date='2026-10-28';old_root=$workspace;new_root=$project;moves=$moves;deleted=$deleted;protected_before=$protected;personal_materials='left_untouched';git='pending_metadata_relocation'}
$audit | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $recordDir '目录整理审计_20261028.json') -Encoding utf8
[pscustomobject]@{moved=$moves.Count;cache_and_render_files_removed=$deleted.Count;removed_bytes=($deleted|Measure-Object bytes -Sum).Sum;protected_files=$protected.Count;project=$project} | ConvertTo-Json
