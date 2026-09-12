import { useEffect, useState, type ReactNode } from 'react';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { darkTheme, lightTheme } from '../theme';
import { initTheme, resolveTheme, subscribeTheme, type ResolvedTheme } from './preference';

initTheme();

export default function ThemeRoot({ children }: { children: ReactNode }) {
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveTheme());

  useEffect(() => subscribeTheme((_preference, nextResolved) => {
    setResolved(nextResolved);
  }), []);

  return (
    <ConfigProvider locale={zhCN} theme={resolved === 'dark' ? darkTheme : lightTheme}>
      {children}
    </ConfigProvider>
  );
}
