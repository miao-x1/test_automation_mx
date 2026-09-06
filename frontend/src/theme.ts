import type { ThemeConfig } from 'antd';

/** 全局高级简约主题：暖灰纸面 + 墨色主按钮，无渐变、无重阴影 */
export const appTheme: ThemeConfig = {
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
