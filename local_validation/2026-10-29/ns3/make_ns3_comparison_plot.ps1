param(
    [Parameter(Mandatory = $true)][string]$SummaryCsv,
    [Parameter(Mandatory = $true)][string]$OutputPng
)

Add-Type -AssemblyName System.Drawing
$rows = Import-Csv -LiteralPath $SummaryCsv
$bitmap = New-Object System.Drawing.Bitmap(1800, 1100)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.Clear([System.Drawing.Color]::White)

$titleFont = New-Object System.Drawing.Font('Arial', 19, [System.Drawing.FontStyle]::Bold)
$panelFont = New-Object System.Drawing.Font('Arial', 13, [System.Drawing.FontStyle]::Bold)
$axisFont = New-Object System.Drawing.Font('Arial', 9)
$labelFont = New-Object System.Drawing.Font('Arial', 8)
$brush = [System.Drawing.Brushes]::Black
$gridPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(220, 220, 220), 1)
$axisPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(50, 50, 50), 1)
$palette = @(
    [System.Drawing.Color]::FromArgb(45, 93, 150),
    [System.Drawing.Color]::FromArgb(139, 173, 211),
    [System.Drawing.Color]::FromArgb(176, 55, 55),
    [System.Drawing.Color]::FromArgb(224, 147, 147)
)

function Get-NumberOrNull([object]$Value) {
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value) -or [string]$Value -eq 'NA') {
        return $null
    }
    return [double]$Value
}

function Draw-Panel(
    [System.Drawing.Graphics]$Canvas,
    [string]$Scenario,
    [string]$Metric,
    [string]$ValueField,
    [string]$CiField,
    [int]$Left,
    [int]$Top,
    [int]$PanelWidth,
    [int]$PanelHeight
) {
    $Canvas.DrawString("$Scenario : $Metric", $panelFont, $brush, $Left, $Top)
    $plotLeft = $Left + 76
    $plotTop = $Top + 43
    $plotWidth = $PanelWidth - 103
    $plotHeight = $PanelHeight - 108

    $selected = @($rows | Where-Object { $_.experiment -eq $Scenario })
    $records = @()
    foreach ($routing in @('aodv', 'olsr')) {
        foreach ($model in @('ns-3.49', 'Python_R1_abstraction')) {
            $row = $selected | Where-Object {
                $_.routing -eq $routing -and $_.simulator -eq $model
            } | Select-Object -First 1
            if ($null -eq $row) {
                $value = $null
                $ci = $null
            }
            else {
                $value = Get-NumberOrNull $row.$ValueField
                $ci = Get-NumberOrNull $row.$CiField
            }
            $labelModel = if ($model -eq 'ns-3.49') { 'ns-3' } else { 'R1' }
            $labelRouting = if ($routing -eq 'aodv') { 'AODV' } else { 'OLSR' }
            $records += [pscustomobject]@{
                Label = "$labelModel $labelRouting"
                Value = $value
                Ci = $ci
                Color = $palette[$records.Count]
            }
        }
    }

    if ($Metric -eq 'PDR') {
        $maxY = 1.05
        $tickStep = 0.25
        $digits = '0.00'
    }
    else {
        $values = @($records | Where-Object { $null -ne $_.Value } | ForEach-Object {
            $_.Value + $(if ($null -ne $_.Ci) { $_.Ci } else { 0 })
        })
        $maxY = if ($values.Count -gt 0) { [math]::Ceiling(($values | Measure-Object -Maximum).Maximum / 10) * 10 } else { 1 }
        if ($maxY -le 0) { $maxY = 1 }
        $tickStep = $maxY / 4
        $digits = '0.##'
    }

    for ($i = 0; $i -le 4; $i++) {
        $value = $tickStep * $i
        $y = $plotTop + $plotHeight - [int](($value / $maxY) * $plotHeight)
        $Canvas.DrawLine($gridPen, $plotLeft, $y, $plotLeft + $plotWidth, $y)
        $label = $value.ToString($digits, [System.Globalization.CultureInfo]::InvariantCulture)
        $Canvas.DrawString($label, $axisFont, $brush, $Left + 4, $y - 8)
    }
    $Canvas.DrawLine($axisPen, $plotLeft, $plotTop, $plotLeft, $plotTop + $plotHeight)
    $Canvas.DrawLine($axisPen, $plotLeft, $plotTop + $plotHeight, $plotLeft + $plotWidth, $plotTop + $plotHeight)

    $slotWidth = $plotWidth / $records.Count
    $barWidth = [math]::Min(62, $slotWidth * 0.62)
    for ($i = 0; $i -lt $records.Count; $i++) {
        $record = $records[$i]
        $centerX = $plotLeft + ($i * $slotWidth) + ($slotWidth / 2)
        if ($null -eq $record.Value) {
            $Canvas.DrawString('NA', $labelFont, $brush, [single]($centerX - 10), [single]($plotTop + $plotHeight - 22))
        }
        else {
            $barHeight = [int](($record.Value / $maxY) * $plotHeight)
            $barX = [int]($centerX - $barWidth / 2)
            $barY = $plotTop + $plotHeight - $barHeight
            $barBrush = New-Object System.Drawing.SolidBrush($record.Color)
            $Canvas.FillRectangle($barBrush, $barX, $barY, [int]$barWidth, $barHeight)
            $barBrush.Dispose()
            if ($null -ne $record.Ci) {
                $upper = [math]::Min($maxY, $record.Value + $record.Ci)
                $lower = [math]::Max(0, $record.Value - $record.Ci)
                $yUpper = $plotTop + $plotHeight - [int](($upper / $maxY) * $plotHeight)
                $yLower = $plotTop + $plotHeight - [int](($lower / $maxY) * $plotHeight)
                $Canvas.DrawLine($axisPen, [int]$centerX, $yUpper, [int]$centerX, $yLower)
                $Canvas.DrawLine($axisPen, [int]($centerX - 5), $yUpper, [int]($centerX + 5), $yUpper)
                $Canvas.DrawLine($axisPen, [int]($centerX - 5), $yLower, [int]($centerX + 5), $yLower)
            }
        }
        $labelRect = New-Object System.Drawing.RectangleF([single]($centerX - $slotWidth / 2), [single]($plotTop + $plotHeight + 7), [single]$slotWidth, 28)
        $format = New-Object System.Drawing.StringFormat
        $format.Alignment = [System.Drawing.StringAlignment]::Center
        $Canvas.DrawString($record.Label, $labelFont, $brush, $labelRect, $format)
        $format.Dispose()
    }
}

$graphics.DrawString('Paired ns-3.49 and R1 replay results (error bars: 95% Student-t CI half-width)', $titleFont, $brush, 58, 24)
Draw-Panel $graphics 'C' 'PDR' 'mean_pdr' 'pdr_t95_half_width' 50 80 825 470
Draw-Panel $graphics 'C' 'Latency (ms)' 'mean_latency_ms' 'latency_t95_half_width_ms' 920 80 825 470
Draw-Panel $graphics 'D' 'PDR' 'mean_pdr' 'pdr_t95_half_width' 50 580 825 470
Draw-Panel $graphics 'D' 'Latency (ms)' 'mean_latency_ms' 'latency_t95_half_width_ms' 920 580 825 470

$parent = Split-Path -Parent $OutputPng
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
$bitmap.Save($OutputPng, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
$titleFont.Dispose()
$panelFont.Dispose()
$axisFont.Dispose()
$labelFont.Dispose()
$gridPen.Dispose()
$axisPen.Dispose()
Write-Output "Wrote $OutputPng"
