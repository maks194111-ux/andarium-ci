// SPDX-License-Identifier: MIT
package local.andarium.probe;

import android.app.Activity;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;

/** A settings-like list drawn by the platform's own renderer, in a debuggable
 *  package so that the shell may sample its threads. */
public class ProbeActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        final float density = getResources().getDisplayMetrics().density;
        ListView list = new ListView(this);
        list.setAdapter(new BaseAdapter() {
            @Override public int getCount() { return 400; }
            @Override public Object getItem(int position) { return position; }
            @Override public long getItemId(int position) { return position; }
            @Override public View getView(int position, View reused, ViewGroup parent) {
                LinearLayout row = (LinearLayout) reused;
                if (row == null) {
                    row = new LinearLayout(ProbeActivity.this);
                    row.setOrientation(LinearLayout.HORIZONTAL);
                    row.setGravity(Gravity.CENTER_VERTICAL);
                    int pad = (int) (16 * density);
                    row.setPadding(pad, pad, pad, pad);
                    View icon = new View(ProbeActivity.this);
                    GradientDrawable circle = new GradientDrawable();
                    circle.setShape(GradientDrawable.OVAL);
                    icon.setBackground(circle);
                    row.addView(icon, new LinearLayout.LayoutParams((int) (40 * density), (int) (40 * density)));
                    LinearLayout text = new LinearLayout(ProbeActivity.this);
                    text.setOrientation(LinearLayout.VERTICAL);
                    text.setPadding(pad, 0, 0, 0);
                    TextView title = new TextView(ProbeActivity.this);
                    title.setTextSize(18);
                    TextView summary = new TextView(ProbeActivity.this);
                    summary.setTextSize(14);
                    text.addView(title);
                    text.addView(summary);
                    row.addView(text);
                }
                ((GradientDrawable) row.getChildAt(0).getBackground())
                        .setColor(0xff000000 | (int) (position * 2654435761L & 0xffffff));
                LinearLayout text = (LinearLayout) row.getChildAt(1);
                ((TextView) text.getChildAt(0)).setText("Network and internet " + position);
                ((TextView) text.getChildAt(1)).setText("Mobile, Wi-Fi, hotspot, row " + position);
                return row;
            }
        });
        setContentView(list);
    }
}
