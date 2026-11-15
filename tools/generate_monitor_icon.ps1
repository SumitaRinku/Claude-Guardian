param(
    [string]$OutputDir = (Join-Path $PSScriptRoot '..\skills\claude-guardian\assets\monitor'),
    # Optional: also write a review sheet (every size on light and dark taskbar colours, enlarged).
    [string]$PreviewPath = '',
    # shield: status-coloured shield with a white mark. brand: clay shield carrying the
    # Claude mark, with a status lamp badge. lamp: plain status lamp.
    [ValidateSet('shield', 'brand', 'lamp')][string]$Style = 'shield',
    [string]$Logo = (Join-Path $PSScriptRoot '..\skills\claude-guardian\assets\killswitch\icon.png')
)
# Status lamp icons for the monitor tray and window. Drawn per size on the pixel grid
# (not downscaled from one large image), so 16 px stays crisp. Needs only System.Drawing.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

function Rgb([string]$hex) { [System.Drawing.ColorTranslator]::FromHtml($hex) }

# Lamp fill (light top, base bottom) and rim; vivid enough for both light and dark taskbars.
$states = [ordered]@{
    ok       = @{ Top = (Rgb '#4cc285'); Base = (Rgb '#249358'); Rim = (Rgb '#17663c'); Glyph = 'check' }
    degraded = @{ Top = (Rgb '#ffc94d'); Base = (Rgb '#e09a12'); Rim = (Rgb '#9c6608'); Glyph = 'bang' }
    fail     = @{ Top = (Rgb '#f26a5e'); Base = (Rgb '#d1342a'); Rim = (Rgb '#8f1f18'); Glyph = 'cross' }
    unknown  = @{ Top = (Rgb '#a7adb6'); Base = (Rgb '#7b828d'); Rim = (Rgb '#525861'); Glyph = 'dash' }
}
$sizes = @(16, 20, 24, 32, 48, 64, 256)
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

function Draw-Glyph($g, [string]$kind, [single]$size, [single]$c) {
    # Stroke width snaps to whole pixels at small sizes so the mark does not blur.
    $w = [single][Math]::Max(2, [Math]::Round($size * 0.11))
    $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::White, $w)
    $pen.StartCap = 'Round'; $pen.EndCap = 'Round'; $pen.LineJoin = 'Round'
    $u = $size / 16.0
    switch ($kind) {
        'check' {
            $pts = [System.Drawing.PointF[]]@(
                (New-Object System.Drawing.PointF(($c - 3.6 * $u), ($c + 0.2 * $u))),
                (New-Object System.Drawing.PointF(($c - 1.1 * $u), ($c + 2.7 * $u))),
                (New-Object System.Drawing.PointF(($c + 3.7 * $u), ($c - 2.4 * $u))))
            $g.DrawLines($pen, $pts)
        }
        'cross' {
            $d = 2.9 * $u
            $g.DrawLine($pen, ($c - $d), ($c - $d), ($c + $d), ($c + $d))
            $g.DrawLine($pen, ($c - $d), ($c + $d), ($c + $d), ($c - $d))
        }
        'bang' {
            $g.DrawLine($pen, $c, ($c - 3.6 * $u), $c, ($c + 0.6 * $u))
            $dot = $w * 1.05
            $g.FillEllipse([System.Drawing.Brushes]::White, ($c - $dot / 2), ($c + 2.9 * $u - $dot / 2), $dot, $dot)
        }
        'dash' {
            $g.DrawLine($pen, ($c - 3.2 * $u), $c, ($c + 3.2 * $u), $c)
        }
    }
    $pen.Dispose()
}

function New-ShieldPath([single]$size) {
    # Shield outline on a 16-unit grid, scaled to the frame: flat shoulders, pointed base.
    $u = $size / 16.0
    function P([double]$x, [double]$y) { New-Object System.Drawing.PointF(($x * $u), ($y * $u)) }
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddBezier((P 8 0.5), (P 10.2 1.8), (P 12.6 2.3), (P 15 2.3))
    $path.AddLine((P 15 2.3), (P 15 7.0))
    $path.AddBezier((P 15 7.0), (P 15 11.3), (P 12.0 14.2), (P 8 15.6))
    $path.AddBezier((P 8 15.6), (P 4.0 14.2), (P 1 11.3), (P 1 7.0))
    $path.AddLine((P 1 7.0), (P 1 2.3))
    $path.AddBezier((P 1 2.3), (P 3.4 2.3), (P 5.8 1.8), (P 8 0.5))
    $path.CloseFigure()
    return $path
}

function Fill-Shield($g, [int]$size, $top, $base, $rimColor) {
    $path = New-ShieldPath ([single]$size)
    $bounds = New-Object System.Drawing.RectangleF(0, 0, $size, $size)
    $fill = New-Object System.Drawing.Drawing2D.LinearGradientBrush($bounds, $top, $base, [single]90)
    $g.FillPath($fill, $path)
    $fill.Dispose()
    if ($size -ge 32) {
        $g.SetClip($path)
        $hl = New-Object System.Drawing.RectangleF(0, 0, $size, ($size * 0.45))
        $hb = New-Object System.Drawing.Drawing2D.LinearGradientBrush($hl,
            [System.Drawing.Color]::FromArgb(70, 255, 255, 255), [System.Drawing.Color]::FromArgb(0, 255, 255, 255), [single]90)
        $g.FillRectangle($hb, $hl)
        $hb.Dispose()
        $g.ResetClip()
    }
    $rim = New-Object System.Drawing.Pen($rimColor, [single][Math]::Max(1, [Math]::Round($size / 24.0)))
    $rim.LineJoin = 'Round'
    $g.DrawPath($rim, $path)
    $rim.Dispose()
    $path.Dispose()
}

$script:logoImage = $null
function Draw-WhiteLogo($g, [single]$x, [single]$y, [single]$d) {
    if (-not $script:logoImage) { $script:logoImage = [System.Drawing.Image]::FromFile((Resolve-Path $Logo)) }
    # Recolour the mark to white, keeping its alpha.
    $matrix = New-Object System.Drawing.Imaging.ColorMatrix
    $matrix.Matrix00 = 0; $matrix.Matrix11 = 0; $matrix.Matrix22 = 0
    $matrix.Matrix40 = 1; $matrix.Matrix41 = 1; $matrix.Matrix42 = 1
    $attributes = New-Object System.Drawing.Imaging.ImageAttributes
    $attributes.SetColorMatrix($matrix)
    $dest = New-Object System.Drawing.Rectangle([int]$x, [int]$y, [int]$d, [int]$d)
    $g.DrawImage($script:logoImage, $dest, 0, 0, $script:logoImage.Width, $script:logoImage.Height, 'Pixel', $attributes)
    $attributes.Dispose()
}

function New-Bitmap([int]$size, $spec) {
    $bitmap = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bitmap)
    $g.SmoothingMode = 'AntiAlias'
    $g.PixelOffsetMode = 'HighQuality'
    $g.InterpolationMode = 'HighQualityBicubic'
    $g.Clear([System.Drawing.Color]::Transparent)

    if ($Style -eq 'shield') {
        Fill-Shield $g $size $spec.Top $spec.Base $spec.Rim
        # Glyph sits slightly above centre, where the shield is widest.
        $g.TranslateTransform(0, [single](-$size * 0.03))
        $g.ScaleTransform(0.9, 0.9)
        $g.TranslateTransform([single]($size * 0.0556), [single]($size * 0.0556))
        Draw-Glyph $g $spec.Glyph ([single]$size) ([single]($size / 2.0))
        $g.Dispose()
        return $bitmap
    }

    if ($Style -eq 'brand') {
        Fill-Shield $g $size (Rgb '#e07a55') (Rgb '#c15f3c') (Rgb '#8a3f24')
        if ($size -ge 24) {
            $d = $size * 0.46
            Draw-WhiteLogo $g ($size * 0.12) ($size * 0.14) $d
        }
        # Status lamp badge in the lower right; large enough to read at 16 px.
        $badge = [single][Math]::Round($size * 0.52)
        $bx = $size - $badge; $by = $size - $badge
        $ring = [single][Math]::Max(1, [Math]::Round($size / 16.0))
        $g.FillEllipse([System.Drawing.Brushes]::White, ($bx - $ring), ($by - $ring), ($badge + $ring), ($badge + $ring))
        $rect = New-Object System.Drawing.RectangleF($bx, $by, ($badge - 1), ($badge - 1))
        $fill = New-Object System.Drawing.Drawing2D.LinearGradientBrush($rect, $spec.Top, $spec.Base, [single]90)
        $g.FillEllipse($fill, $rect)
        $fill.Dispose()
        if ($size -ge 24) {
            $g.TranslateTransform(($bx), ($by))
            Draw-Glyph $g $spec.Glyph ([single]$badge) ([single]($badge / 2.0))
        }
        $g.Dispose()
        return $bitmap
    }

    # The lamp fills the frame, leaving half a pixel so the rim is not clipped.
    $inset = [single]0.5
    $d = [single]($size - 1)
    $rect = New-Object System.Drawing.RectangleF($inset, $inset, $d, $d)
    $fill = New-Object System.Drawing.Drawing2D.LinearGradientBrush($rect, $spec.Top, $spec.Base, [single]90)
    $g.FillEllipse($fill, $rect)
    $fill.Dispose()

    if ($size -ge 32) {
        # Soft top highlight gives a lamp-like depth at window and Explorer sizes only.
        $hl = New-Object System.Drawing.RectangleF(($size * 0.2), ($size * 0.07), ($size * 0.6), ($size * 0.42))
        $hb = New-Object System.Drawing.Drawing2D.LinearGradientBrush($hl,
            [System.Drawing.Color]::FromArgb(90, 255, 255, 255), [System.Drawing.Color]::FromArgb(0, 255, 255, 255), [single]90)
        $g.FillEllipse($hb, $hl)
        $hb.Dispose()
    }

    $rimWidth = [single][Math]::Max(1, [Math]::Round($size / 24.0))
    $rim = New-Object System.Drawing.Pen($spec.Rim, $rimWidth)
    $half = $rimWidth / 2
    $g.DrawEllipse($rim, ($inset + $half - 0.5), ($inset + $half - 0.5), ($d - $rimWidth + 1), ($d - $rimWidth + 1))
    $rim.Dispose()

    Draw-Glyph $g $spec.Glyph ([single]$size) ([single]($size / 2.0))
    $g.Dispose()
    return $bitmap
}

function To-Png($bitmap) {
    $stream = New-Object IO.MemoryStream
    $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
    # The leading comma stops PowerShell from unrolling the byte array into the pipeline.
    return ,$stream.ToArray()
}

function To-Dib($bitmap) {
    # Classic 32-bit ICO frame (BITMAPINFOHEADER + bottom-up BGRA + AND mask). Every Windows
    # icon loader reads it; PNG frames are kept for 256 px only, where they are standard.
    $size = $bitmap.Width
    $rect = New-Object System.Drawing.Rectangle(0, 0, $size, $size)
    $data = $bitmap.LockBits($rect, 'ReadOnly', [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $stride = $size * 4
    $pixels = New-Object byte[] ($stride * $size)
    for ($row = 0; $row -lt $size; $row++) {
        [Runtime.InteropServices.Marshal]::Copy([IntPtr]($data.Scan0.ToInt64() + $row * $data.Stride), $pixels, ($size - 1 - $row) * $stride, $stride)
    }
    $bitmap.UnlockBits($data)
    $maskStride = [int]([Math]::Ceiling($size / 32.0) * 4)
    $stream = New-Object IO.MemoryStream
    $writer = New-Object IO.BinaryWriter($stream)
    $writer.Write([uint32]40); $writer.Write([int32]$size); $writer.Write([int32]($size * 2))
    $writer.Write([uint16]1); $writer.Write([uint16]32); $writer.Write([uint32]0)
    $writer.Write([uint32]($pixels.Length + $maskStride * $size))
    $writer.Write([int32]0); $writer.Write([int32]0); $writer.Write([uint32]0); $writer.Write([uint32]0)
    $writer.Write($pixels)
    $writer.Write((New-Object byte[] ($maskStride * $size)))
    $writer.Flush()
    return ,$stream.ToArray()
}

function Write-Ico([string]$path, $frames) {
    $stream = New-Object IO.MemoryStream
    $writer = New-Object IO.BinaryWriter($stream)
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$frames.Count)
    $offset = 6 + 16 * $frames.Count
    foreach ($frame in $frames) {
        $dim = 0
        if ($frame.Size -lt 256) { $dim = $frame.Size }
        $writer.Write([byte]$dim)
        $writer.Write([byte]$dim)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$frame.Bytes.Length)
        $writer.Write([uint32]$offset)
        $offset += $frame.Bytes.Length
    }
    foreach ($frame in $frames) { $writer.Write($frame.Bytes) }
    $writer.Flush()
    [IO.File]::WriteAllBytes($path, $stream.ToArray())
}

$rendered = @{}
foreach ($name in $states.Keys) {
    $frames = @()
    $rendered[$name] = @{}
    foreach ($size in $sizes) {
        $bitmap = New-Bitmap $size $states[$name]
        $bytes = if ($size -ge 256) { To-Png $bitmap } else { To-Dib $bitmap }
        $frames += [pscustomobject]@{ Size = $size; Bytes = $bytes }
        $rendered[$name][$size] = $bitmap
    }
    Write-Ico (Join-Path $OutputDir ('icon-' + $name + '.ico')) $frames
    # 128 px PNG per state for the panel header (Tk PhotoImage reads PNG, not ICO).
    $headerLogo = New-Bitmap 128 $states[$name]
    $headerLogo.Save((Join-Path $OutputDir ('logo-' + $name + '.png')), [System.Drawing.Imaging.ImageFormat]::Png)
    $headerLogo.Dispose()
    if ($name -eq 'ok') {
        [IO.File]::WriteAllBytes((Join-Path $OutputDir 'icon.png'), ($frames | Where-Object { $_.Size -eq 256 }).Bytes)
    }
}

if ($PreviewPath) {
    # Rows: light taskbar, dark taskbar. Each small size is shown 1:1 and enlarged 6x (nearest neighbour).
    $small = @(16, 20, 24, 32)
    $zoom = 6
    $cell = 32 * $zoom + 24
    $sheet = New-Object System.Drawing.Bitmap((4 * ($cell * $small.Count + 140)), (2 * ($cell + 60)))
    $g = [System.Drawing.Graphics]::FromImage($sheet)
    $g.InterpolationMode = 'NearestNeighbor'
    $g.PixelOffsetMode = 'Half'
    $backgrounds = @((Rgb '#f3f3f3'), (Rgb '#1f1f1f'))
    for ($row = 0; $row -lt 2; $row++) {
        $y = $row * ($cell + 60)
        $g.FillRectangle((New-Object System.Drawing.SolidBrush($backgrounds[$row])), 0, $y, $sheet.Width, ($cell + 60))
        $x = 20
        foreach ($name in $states.Keys) {
            foreach ($size in $small) {
                $bmp = $rendered[$name][$size]
                $g.DrawImage($bmp, $x, ($y + 16), $size, $size)
                $g.DrawImage($bmp, $x, ($y + 56), ($size * $zoom), ($size * $zoom))
                $x += $size * $zoom + 24
            }
            $x += 140 - 24 * 0
        }
    }
    $g.Dispose()
    $sheet.Save($PreviewPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $sheet.Dispose()
}
foreach ($name in $rendered.Keys) { foreach ($bmp in $rendered[$name].Values) { $bmp.Dispose() } }
"written state icons: " + (($states.Keys | ForEach-Object { 'icon-' + $_ + '.ico' }) -join ', ')
