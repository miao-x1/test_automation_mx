/**
 * 测试用例中心（统一）
 *
 * 布局：左目录树 | 右列表（Tab切换）
 * Tab：Generate / Draft / Review / Publish / History
 *
 * 用户视角：测试用例（非"测试资产"）
 * 内部模型：TestAsset
 * 路由：/test-cases
 */
import { useState, useCallback } from 'react';
import { Layout, Tree, Card, Tabs, Row, Col, Statistic, Button } from 'antd';
import {
  ApiOutlined, GlobalOutlined, AndroidOutlined, DesktopOutlined,
  RobotOutlined, InboxOutlined, CloudUploadOutlined, FolderOutlined,
} from '@ant-design/icons';
import DraftPage from './DraftPage';
import ReviewPage from './ReviewPage';
import PublishPage from './PublishPage';
import HistoryPage from './HistoryPage';
import GeneratePage from './GeneratePage';
import AssetDetailDrawer from './AssetDetailDrawer';

const { Sider: InnerSider, Content: InnerContent } = Layout;

const treeData = [
  {
    title: '全部用例', key: 'all', icon: <FolderOutlined />,
    children: [
      { title: 'API测试', key: 'api', icon: <ApiOutlined /> },
      { title: 'Web测试', key: 'web', icon: <GlobalOutlined /> },
      { title: 'Android测试', key: 'android', icon: <AndroidOutlined /> },
      { title: '通用用例', key: 'manual', icon: <DesktopOutlined /> },
    ],
  },
];

export default function TestAssetsPage() {
  const [activeTab, setActiveTab] = useState('draft');
  const [selectedType, setSelectedType] = useState<string>('all');
  const [detailAssetId, setDetailAssetId] = useState<number | null>(null);
  const [detailVisible, setDetailVisible] = useState(false);
  const [typeStats, setTypeStats] = useState<Record<string, number>>({ api: 0, web: 0, android: 0, manual: 0 });
  const [refreshKey, setRefreshKey] = useState(0);

  // 加载统计
  const loadStats = useCallback(async () => {
    try {
      const res = await fetch('/api/assets/v2/stats/summary', { credentials: 'include' });
      const data = await res.json();
      if (data.stats) {
        const s: Record<string, number> = { api: 0, web: 0, android: 0, manual: 0 };
        for (const [type, statuses] of Object.entries(data.stats)) {
          for (const count of Object.values(statuses as Record<string, number>)) {
            s[type] = (s[type] || 0) + count;
          }
        }
        setTypeStats(s);
      }
    } catch { /* ignore */ }
  }, []);

  useState(() => { loadStats(); });

  const handleDetail = (id: number) => {
    setDetailAssetId(id);
    setDetailVisible(true);
  };

  const handleRefresh = () => {
    setRefreshKey(k => k + 1);
    loadStats();
  };

  const tabItems = [
    {
      key: 'generate',
      label: <span><RobotOutlined /> AI生成</span>,
      children: <GeneratePage />,
    },
    {
      key: 'draft',
      label: <span><InboxOutlined /> 草稿</span>,
      children: <DraftPage key={`draft-${refreshKey}`} onDetail={handleDetail} />,
    },
    {
      key: 'review',
      label: <span><FolderOutlined /> 审查</span>,
      children: <ReviewPage key={`review-${refreshKey}`} onDetail={handleDetail} />,
    },
    {
      key: 'publish',
      label: <span><GlobalOutlined /> 发布</span>,
      children: <PublishPage key={`publish-${refreshKey}`} onDetail={handleDetail} />,
    },
    {
      key: 'history',
      label: <span><DesktopOutlined /> 历史</span>,
      children: <HistoryPage key={`history-${refreshKey}`} onDetail={handleDetail} />,
    },
  ];

  return (
    <div>
      {/* 顶部统计 */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={4}>
          <Card size="small" hoverable onClick={() => setSelectedType('api')}>
            <Statistic title="API测试" value={typeStats.api || 0} prefix={<ApiOutlined style={{ color: '#1890ff' }} />} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" hoverable onClick={() => setSelectedType('web')}>
            <Statistic title="Web测试" value={typeStats.web || 0} prefix={<GlobalOutlined style={{ color: '#52c41a' }} />} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" hoverable onClick={() => setSelectedType('android')}>
            <Statistic title="Android测试" value={typeStats.android || 0} prefix={<AndroidOutlined style={{ color: '#fa8c16' }} />} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" hoverable onClick={() => setSelectedType('manual')}>
            <Statistic title="通用用例" value={typeStats.manual || 0} prefix={<DesktopOutlined style={{ color: '#722ed1' }} />} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="用例总计" value={Object.values(typeStats).reduce((a, b) => a + b, 0)} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Button icon={<CloudUploadOutlined />} onClick={handleRefresh} block>刷新统计</Button>
          </Card>
        </Col>
      </Row>

      {/* 左目录树 + 右Tab列表 */}
      <Layout style={{ background: 'transparent' }}>
        <InnerSider width={180} style={{ background: '#fff', borderRadius: 6, marginRight: 12, padding: '8px 0' }}>
          <Tree
            showIcon
            defaultExpandAll
            selectedKeys={[selectedType]}
            treeData={treeData}
            onSelect={(keys) => {
              if (keys.length > 0) setSelectedType(keys[0] as string);
            }}
          />
        </InnerSider>
        <InnerContent style={{ background: 'transparent' }}>
          <Card size="small" bodyStyle={{ padding: '0 12px 12px' }}>
            <Tabs
              activeKey={activeTab}
              onChange={setActiveTab}
              items={tabItems}
            />
          </Card>
        </InnerContent>
      </Layout>

      {/* 用例详情抽屉 */}
      <AssetDetailDrawer
        assetId={detailAssetId}
        visible={detailVisible}
        onClose={() => { setDetailVisible(false); setDetailAssetId(null); }}
        onRefresh={handleRefresh}
      />
    </div>
  );
}
