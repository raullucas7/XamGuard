# makes the logo pngs the window uses from xamguard/assets/guardian_source.png
# run it with:  powershell -File tools/make_logo.ps1
# no Pillow needed, it only uses the image library that comes with windows

Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public static class LogoMaker {
    // the logo is black ink on a see-through background, so only the alpha channel matters.
    // shrink by averaging the alpha under each new pixel, then boost it so thin lines don't fade
    public static void Make(string srcPath, string outPath, int outH, double boost, double gamma) {
        using (var src = new Bitmap(srcPath)) {
            int sw = src.Width, sh = src.Height;
            var d = src.LockBits(new Rectangle(0, 0, sw, sh), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            byte[] px = new byte[d.Stride * sh];
            Marshal.Copy(d.Scan0, px, 0, px.Length);
            int stride = d.Stride;
            src.UnlockBits(d);

            double scale = (double)outH / sh;
            int outW = (int)Math.Round(sw * scale);
            using (var dst = new Bitmap(outW, outH, PixelFormat.Format32bppArgb)) {
                var dd = dst.LockBits(new Rectangle(0, 0, outW, outH), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
                byte[] o = new byte[dd.Stride * outH];
                for (int y = 0; y < outH; y++) {
                    for (int x = 0; x < outW; x++) {
                        double x0 = x / scale, x1 = (x + 1) / scale, y0 = y / scale, y1 = (y + 1) / scale;
                        double sum = 0, wsum = 0;
                        for (int sy = (int)Math.Floor(y0); sy < Math.Min(sh, (int)Math.Ceiling(y1)); sy++) {
                            double wy = Math.Min(y1, sy + 1) - Math.Max(y0, sy);
                            for (int sx = (int)Math.Floor(x0); sx < Math.Min(sw, (int)Math.Ceiling(x1)); sx++) {
                                double wx = Math.Min(x1, sx + 1) - Math.Max(x0, sx);
                                sum += wx * wy * px[sy * stride + sx * 4 + 3];
                                wsum += wx * wy;
                            }
                        }
                        double a = (wsum > 0 ? sum / wsum : 0) / 255.0;
                        a = Math.Pow(Math.Min(1.0, a * boost), gamma);
                        o[y * dd.Stride + x * 4 + 3] = (byte)Math.Round(a * 255.0);  // B, G, R stay 0 = black
                    }
                }
                Marshal.Copy(o, 0, dd.Scan0, o.Length);
                dst.UnlockBits(dd);
                dst.Save(outPath, ImageFormat.Png);
            }
        }
    }
}
"@

$assets = Join-Path (Split-Path $PSScriptRoot) "xamguard\assets"
$source = Join-Path $assets "guardian_source.png"

# display scaling in percent -> height in pixels (88 px is the size at 100%)
$sizes = @{ 100 = 88; 125 = 110; 150 = 132; 200 = 176 }

foreach ($percent in $sizes.Keys) {
    $out = Join-Path $assets "guardian_$percent.png"
    [LogoMaker]::Make($source, $out, $sizes[$percent], 1.5, 0.7)
    "made $out ($($sizes[$percent]) px tall)"
}
