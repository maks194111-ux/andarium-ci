// SPDX-License-Identifier: MIT
package local.andarium.probe;

import android.app.Activity;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.os.Bundle;
import android.view.View;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Rows that each draw text, or what text drawing is made of, a different way,
 *  so a screenshot shows which part of the GPU text path fails. */
public class TextProbeActivity extends Activity {
    private TextView label(String text, float size) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(size);
        view.setTextColor(Color.BLACK);
        return view;
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        column.setBackgroundColor(Color.WHITE);
        column.setPadding(24, 24, 24, 24);

        column.addView(label("1 GPU text 18sp", 18));

        TextView software = label("2 software layer text", 18);
        software.setLayerType(View.LAYER_TYPE_SOFTWARE, null);
        column.addView(software);

        column.addView(label("3 BIG", 90));

        // 4: text turned into a path, filled by the GPU path renderer.
        final Paint pathPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        pathPaint.setTextSize(54);
        pathPaint.setColor(Color.BLACK);
        View pathText = new View(this) {
            @Override protected void onDraw(Canvas canvas) {
                Path path = new Path();
                pathPaint.getTextPath("4 path text", 0, 11, 0, 50, path);
                canvas.drawPath(path, pathPaint);
            }
        };
        column.addView(pathText, new LinearLayout.LayoutParams(-1, 70));

        // 5: an ALPHA_8 bitmap tinted black (one-channel texture upload).
        Bitmap alpha = Bitmap.createBitmap(300, 40, Bitmap.Config.ALPHA_8);
        alpha.eraseColor(0xff000000);
        ImageView alphaView = new ImageView(this);
        alphaView.setImageBitmap(alpha);
        alphaView.setColorFilter(Color.BLACK);
        column.addView(alphaView);
        column.addView(label("5 above: ALPHA_8 bar", 14));

        // 6: an RGBA bitmap holding software-drawn text.
        Bitmap rgba = Bitmap.createBitmap(500, 60, Bitmap.Config.ARGB_8888);
        Canvas cpu = new Canvas(rgba);
        Paint cpuPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        cpuPaint.setTextSize(40);
        cpuPaint.setColor(Color.BLACK);
        cpu.drawText("6 bitmap text", 0, 45, cpuPaint);
        ImageView rgbaView = new ImageView(this);
        rgbaView.setImageBitmap(rgba);
        column.addView(rgbaView);

        // 7: colored (non-black) GPU text.
        TextView red = label("7 red GPU text", 22);
        red.setTextColor(Color.RED);
        column.addView(red);

        setContentView(column);
    }
}
