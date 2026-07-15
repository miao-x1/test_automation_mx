/**
 * PageRelationPanel - 页面关联面板
 *
 * 三种模式：
 * 1. 自动发现 — AI从需求中推理关联页面
 * 2. 手动选择 — 用户手动添加页面关联
 * 3. 历史流程 — 复用历史任务的页面流程
 *
 * 展示：
 * - 页面缩略图 + 名称 + 关联强度
 * - 页面间连线（流程方向）
 * - 支持拖拽排序
 */
import { useState, useCallback } from 'react';
import {
  Card, Button, Space, Tag, Typography, Empty, Input, List,
  Modal, message, Tooltip, Badge, Radio, Collapse,
} from 'antd';
import {
  ApartmentOutlined, SearchOutlined, PlusOutlined,
  HistoryOutlined, RobotOutlined,
  GlobalOutlined, ArrowRightOutlined,
} from '@ant-design/icons';
import {
  discoverPages, buildFlow, getHistoryFlows,
  RelatedPage, PageTransition, HistoryFlow, PageFlow,
} from '../services/pageRelation';

const { Text } = Typography;

interface Props {
  requirement: string;
  keywords?: string[];
  steps?: string[];
  targetUrl?: string;
  onFlowBuilt?: (flow: PageFlow) => void;
}

export function PageRelationPanel({ requirement, keywords, steps, targetUrl, onFlowBuilt }: Props) {
  const [mode, setMode] = useState<'auto' | 'manual' | 'history'>('auto');
  const [loading, setLoading] = useState(false);
  const [pages, setPages] = useState<RelatedPage[]>([]);
  const [transitions, setTransitions] = useState<PageTransition[]>([]);
  const [discoverSource, setDiscoverSource] = useState<string>('');
  const [historyFlows, setHistoryFlows] = useState<HistoryFlow[]>([]);

  // 手动添加
  const [manualModalVisible, setManualModalVisible] = useState(false);
  const [manualSource, setManualSource] = useState('');
  const [manualTarget, setManualTarget] = useState('');
  const [manualTrigger, setManualTrigger] = useState('');

  // 自动发现
  const handleDiscover = useCallback(async () => {
    if (!requirement.trim()) return;
    setLoading(true);
    try {
      const result = await discoverPages({
        requirement: requirement.trim(),
        keywords: keywords || [],
        steps: steps || [],
        target_url: targetUrl || '',
      });
      setPages(result.pages);
      setTransitions(result.relations.map((r: any) => ({
        from_page: r.source || r.from_page || '',
        to_page: r.target || r.to_page || '',
        trigger: r.trigger || '',
        trigger_locator: r.trigger_locator || '',
        confidence: r.confidence || 0.5,
      })));
      setDiscoverSource(result.source);
      message.success(`发现 ${result.pages.length} 个关联页面`);
    } catch {
      message.error('页面关联发现失败');
    }
    setLoading(false);
  }, [requirement, keywords, steps, targetUrl]);

  // 加载历史流程
  const loadHistory = useCallback(async () => {
    setLoading(true);
    try {
      const flows = await getHistoryFlows(10);
      setHistoryFlows(flows);
    } catch {
      message.error('加载历史流程失败');
    }
    setLoading(false);
  }, []);

  // 构建流程
  const handleBuildFlow = useCallback(async () => {
    if (pages.length === 0) {
      message.warning('请先发现或添加关联页面');
      return;
    }
    setLoading(true);
    try {
      const result = await buildFlow({
        requirement: requirement.trim(),
        target_url: targetUrl || '',
      });
      onFlowBuilt?.(result);
      message.success(`页面流程构建完成：${result.page_flow.length} 个页面`);
    } catch {
      message.error('流程构建失败');
    }
    setLoading(false);
  }, [pages, requirement, targetUrl, onFlowBuilt]);

  // 手动添加关联
  const handleManualAdd = () => {
    if (!manualSource.trim() || !manualTarget.trim()) {
      message.warning('请输入源页面和目标页面');
      return;
    }
    // 添加到本地列表
    const newPageIds = [manualSource.trim(), manualTarget.trim()];
    const newPages = [...pages];
    for (const pid of newPageIds) {
      if (!newPages.find(p => p.page_id === pid)) {
        newPages.push({
          page_id: pid,
          title: pid,
          url: pid.startsWith('http') ? pid : '',
          confidence: 1.0,
        });
      }
    }
    setPages(newPages);
    setTransitions(prev => [...prev, {
      from_page: manualSource.trim(),
      to_page: manualTarget.trim(),
      trigger: manualTrigger.trim(),
      trigger_locator: '',
      confidence: 1.0,
    }]);
    setManualModalVisible(false);
    setManualSource('');
    setManualTarget('');
    setManualTrigger('');
    message.success('已添加页面关联');
  };

  // 选择历史流程
  const handleSelectHistory = (historyFlow: HistoryFlow) => {
    const newPages: RelatedPage[] = historyFlow.page_names.map((name: string) => ({
      page_id: name,
      title: name,
      url: '',
      confidence: 0.7,
    }));
    setPages(newPages);
    // 构建线性转换
    const newTransitions: PageTransition[] = [];
    for (let i = 0; i < newPages.length - 1; i++) {
      newTransitions.push({
        from_page: newPages[i].page_id,
        to_page: newPages[i + 1].page_id,
        trigger: '',
        trigger_locator: '',
        confidence: 0.7,
      });
    }
    setTransitions(newTransitions);
    message.success(`已加载历史流程：${historyFlow.page_names.join(' → ')}`);
  };

  // 删除页面
  const handleRemovePage = (pageId: string) => {
    setPages(prev => prev.filter(p => p.page_id !== pageId));
    setTransitions(prev => prev.filter(t => t.from_page !== pageId && t.to_page !== pageId));
  };

  // 渲染页面流程图
  const renderFlowDiagram = () => {
    if (pages.length === 0) return null;

    return (
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8, padding: '12px 0' }}>
        {pages.map((page, i) => (
          <span key={page.page_id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <Tooltip title={`置信度: ${(page.confidence * 100).toFixed(0)}%${page.url ? `\nURL: ${page.url}` : ''}`}>
              <Tag
                color={page.confidence >= 0.8 ? 'green' : page.confidence >= 0.5 ? 'blue' : 'default'}
                closable
                onClose={() => handleRemovePage(page.page_id)}
                style={{ fontSize: 13, padding: '4px 8px' }}
              >
                <GlobalOutlined /> {page.title || page.page_id}
              </Tag>
            </Tooltip>
            {i < pages.length - 1 && (
              <ArrowRightOutlined style={{ color: '#999', fontSize: 12 }} />
            )}
          </span>
        ))}
      </div>
    );
  };

  return (
    <Card
      size="small"
      title={
        <Space>
          <ApartmentOutlined />
          <Text strong>关联页面</Text>
          {pages.length > 0 && <Badge count={pages.length} style={{ backgroundColor: '#1890ff' }} />}
        </Space>
      }
      extra={
        <Space size="small">
          <Radio.Group value={mode} onChange={e => setMode(e.target.value)} size="small" optionType="button">
            <Radio.Button value="auto"><RobotOutlined /> 自动</Radio.Button>
            <Radio.Button value="manual"><PlusOutlined /> 手动</Radio.Button>
            <Radio.Button value="history"><HistoryOutlined /> 历史</Radio.Button>
          </Radio.Group>
        </Space>
      }
    >
      {mode === 'auto' && (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={loading}
            onClick={handleDiscover}
            disabled={!requirement.trim()}
            block
          >
            自动发现关联页面
          </Button>
          {discoverSource && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              发现来源：{discoverSource === 'neo4j' ? '图数据库' : discoverSource === 'llm' ? 'AI推理' : '关键词匹配'}
            </Text>
          )}
        </Space>
      )}

      {mode === 'manual' && (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Button icon={<PlusOutlined />} onClick={() => setManualModalVisible(true)} block>
            手动添加页面关联
          </Button>
          <Text type="secondary" style={{ fontSize: 11 }}>
            手动指定源页面和目标页面的关联关系
          </Text>
        </Space>
      )}

      {mode === 'history' && (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Button icon={<HistoryOutlined />} loading={loading} onClick={loadHistory} block>
            加载历史流程
          </Button>
          {historyFlows.length > 0 && (
            <List
              size="small"
              dataSource={historyFlows}
              renderItem={(item: HistoryFlow) => (
                <List.Item
                  style={{ cursor: 'pointer', padding: '8px 0' }}
                  onClick={() => handleSelectHistory(item)}
                >
                  <List.Item.Meta
                    title={<Text style={{ fontSize: 13 }}>{item.task_name}</Text>}
                    description={
                      <Space size={4} wrap>
                        {item.page_names.map((name: string, i: number) => (
                          <span key={i}>
                            <Tag style={{ fontSize: 11 }}>{name}</Tag>
                            {i < item.page_names.length - 1 && <ArrowRightOutlined style={{ fontSize: 10, color: '#999' }} />}
                          </span>
                        ))}
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          )}
        </Space>
      )}

      {/* 页面流程图 */}
      {renderFlowDiagram()}

      {/* 转换关系列表 */}
      {transitions.length > 0 && (
        <Collapse
          size="small"
          items={[{
            key: 'transitions',
            label: <Text type="secondary" style={{ fontSize: 12 }}>关联关系 ({transitions.length})</Text>,
            children: (
              <List
                size="small"
                dataSource={transitions}
                renderItem={(t: PageTransition) => (
                  <List.Item style={{ padding: '4px 0', fontSize: 12 }}>
                    <Space size={4}>
                      <Tag>{t.from_page}</Tag>
                      <ArrowRightOutlined style={{ fontSize: 10 }} />
                      <Tag>{t.to_page}</Tag>
                      {t.trigger && <Text type="secondary">({t.trigger})</Text>}
                      <Tag color={t.confidence >= 0.8 ? 'green' : 'default'} style={{ fontSize: 11 }}>
                        {(t.confidence * 100).toFixed(0)}%
                      </Tag>
                    </Space>
                  </List.Item>
                )}
              />
            ),
          }]}
        />
      )}

      {/* 构建流程按钮 */}
      {pages.length >= 2 && (
        <Button
          type="primary"
          icon={<ApartmentOutlined />}
          loading={loading}
          onClick={handleBuildFlow}
          style={{ marginTop: 12 }}
          block
        >
          构建完整页面流程
        </Button>
      )}

      {pages.length === 0 && !loading && mode === 'auto' && (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="输入需求后点击自动发现" />
      )}

      {/* 手动添加弹窗 */}
      <Modal
        title="手动添加页面关联"
        open={manualModalVisible}
        onOk={handleManualAdd}
        onCancel={() => setManualModalVisible(false)}
        okText="添加"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <div>
            <Text type="secondary">源页面</Text>
            <Input
              placeholder="如：登录页"
              value={manualSource}
              onChange={e => setManualSource(e.target.value)}
            />
          </div>
          <div>
            <Text type="secondary">目标页面</Text>
            <Input
              placeholder="如：首页"
              value={manualTarget}
              onChange={e => setManualTarget(e.target.value)}
            />
          </div>
          <div>
            <Text type="secondary">触发条件（可选）</Text>
            <Input
              placeholder="如：点击登录按钮"
              value={manualTrigger}
              onChange={e => setManualTrigger(e.target.value)}
            />
          </div>
        </Space>
      </Modal>
    </Card>
  );
}
