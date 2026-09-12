import { useEffect, useState } from 'react';
import { Radio, Typography } from 'antd';
import {
  getThemePreference,
  resolveTheme,
  setThemePreference,
  subscribeTheme,
  type ThemePreference,
} from '@/theme/preference';

const OPTIONS: { value: ThemePreference; label: string; desc: string }[] = [
  { value: 'light', label: '白天', desc: '浅色界面' },
  { value: 'dark', label: '夜间', desc: '深色界面' },
  { value: 'system', label: '跟随系统', desc: '与系统外观保持一致' },
];

export default function AppearanceSettings() {
  const [preference, setPreference] = useState<ThemePreference>(getThemePreference);
  const [resolved, setResolved] = useState(() => resolveTheme(preference));

  useEffect(() => subscribeTheme((nextPreference, nextResolved) => {
    setPreference(nextPreference);
    setResolved(nextResolved);
  }), []);

  return (
    <div>
      <Typography.Title level={5} style={{ marginTop: 0 }}>主题</Typography.Title>
      <Typography.Paragraph type="secondary">
        选择平台外观。当前生效：{resolved === 'dark' ? '夜间' : '白天'}。
      </Typography.Paragraph>
      <Radio.Group
        value={preference}
        onChange={(event) => setThemePreference(event.target.value)}
        optionType="button"
        buttonStyle="solid"
      >
        {OPTIONS.map((item) => (
          <Radio.Button key={item.value} value={item.value}>{item.label}</Radio.Button>
        ))}
      </Radio.Group>
      <div style={{ marginTop: 8, color: 'var(--text-muted)', fontSize: 13 }}>
        {OPTIONS.find((item) => item.value === preference)?.desc}
      </div>
    </div>
  );
}
