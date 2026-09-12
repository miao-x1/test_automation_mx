import type { ThemeConfig } from 'antd';
import { theme } from 'antd';

/** 全局高级简约主题：暖灰纸面 + 墨色主按钮，无渐变、无重阴影 */
export const lightTheme: ThemeConfig = {
  token: {
    colorPrimary: '#1c1c1c',
    colorInfo: '#1c1c1c',
    colorSuccess: '#3d5a45',
    colorWarning: '#8a7348',
    colorError: '#8a3d3d',
    colorText: '#1c1c1c',
    colorTextSecondary: '#6b6560',
    colorBorder: '#e6e1d8',
    colorBorderSecondary: '#efece6',
    colorBgLayout: '#f3f1ec',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    borderRadius: 6,
    fontFamily:
      '"Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
    fontSize: 14,
    controlHeight: 36,
    boxShadow: 'none',
    boxShadowSecondary: 'none',
  },
  components: {
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      dangerShadow: 'none',
    },
    Card: {
      paddingLG: 20,
    },
    Layout: {
      headerBg: '#ffffff',
      bodyBg: '#f3f1ec',
      siderBg: '#141414',
      triggerBg: '#141414',
      triggerColor: '#c8c4bc',
    },
    Menu: {
      darkItemBg: '#141414',
      darkSubMenuItemBg: '#141414',
      darkItemSelectedBg: '#2a2a2a',
      darkItemHoverBg: '#222222',
      darkItemColor: '#c8c4bc',
      darkItemSelectedColor: '#ffffff',
      itemBorderRadius: 4,
    },
    Table: {
      headerBg: '#f7f5f1',
      headerColor: '#6b6560',
      rowHoverBg: '#f7f5f1',
    },
    Input: {
      activeShadow: 'none',
    },
    Tag: {
      defaultBg: '#f7f5f1',
      defaultColor: '#6b6560',
    },
    Tabs: {
      itemActiveColor: '#1c1c1c',
      itemSelectedColor: '#1c1c1c',
      inkBarColor: '#1c1c1c',
    },
    Statistic: {
      contentFontSize: 28,
    },
  },
};

export const darkTheme: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#4493f8',
    colorInfo: '#4493f8',
    colorSuccess: '#3fb950',
    colorWarning: '#d29922',
    colorError: '#f85149',
    colorText: '#e6edf3',
    colorTextSecondary: '#8b949e',
    colorBorder: '#30363d',
    colorBorderSecondary: '#21262d',
    colorBgLayout: '#0d1117',
    colorBgContainer: '#161b22',
    colorBgElevated: '#1c2128',
    borderRadius: 6,
    fontFamily:
      '"Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
    fontSize: 14,
    controlHeight: 36,
    boxShadow: 'none',
    boxShadowSecondary: 'none',
  },
  components: {
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      dangerShadow: 'none',
    },
    Card: {
      paddingLG: 20,
    },
    Layout: {
      headerBg: '#161b22',
      bodyBg: '#0d1117',
      siderBg: '#161b22',
      triggerBg: '#161b22',
      triggerColor: '#8b949e',
    },
    Menu: {
      darkItemBg: '#161b22',
      darkSubMenuItemBg: '#161b22',
      darkItemSelectedBg: '#21262d',
      darkItemHoverBg: '#21262d',
      darkItemColor: '#8b949e',
      darkItemSelectedColor: '#e6edf3',
      itemBorderRadius: 4,
    },
    Table: {
      headerBg: '#21262d',
      headerColor: '#8b949e',
      rowHoverBg: '#21262d',
    },
    Input: {
      activeShadow: 'none',
    },
    Tag: {
      defaultBg: '#21262d',
      defaultColor: '#8b949e',
    },
    Tabs: {
      itemActiveColor: '#e6edf3',
      itemSelectedColor: '#e6edf3',
      inkBarColor: '#4493f8',
    },
    Statistic: {
      contentFontSize: 28,
    },
  },
};

export const appTheme = lightTheme;
