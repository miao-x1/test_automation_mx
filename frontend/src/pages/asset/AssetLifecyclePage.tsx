import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Button, Card, Drawer, Empty, Form, Input, Modal, Select, Space, Table, Tag, Typography, message,
} from 'antd';
import { PlusOutlined, ReloadOutlined, PartitionOutlined } from '@ant-design/icons';
import { getCurrentProjectId, PROJECT_CHANGED } from '@/pages/product/projectStore';
import { PILLARS, PILLAR_BY_STAGE } from '@/pages/product/pillarNav';
import {
  createLifecycleAsset,
  fetchLifecycleAssets,
  fetchLifecycleStages,
  getLifecycleAsset,
  linkLifecycleAsset,
  syncLifecycleAssets,
  updateLifecycleAsset,
  type LifecycleAsset,
  type LifecyclePillar,
  type LifecycleStage,
} from '@/services/assetLifecycle';

const { Title, Paragraph, Text } = Typography;

const FALLBACK_STAGES: LifecycleStage[] = [
  { key: '01_analysis', code: '01', name: '需求分析', order: 1, pillar: 'understand', pillar_name: '项目理解', categories: ['需求文档', '功能清单', '页面分析', '业务流程', '测试范围', '风险点', '页面地图', '页面结构', '页面元素', '业务关系', '用户角色/权限', '接口/API关系', '数据关系', '系统依赖', '项目知识库'] },
  { key: '02_plan', code: '02', name: '测试计划', order: 2, pillar: 'design', pillar_name: '测试设计', categories: ['测试计划', '测试策略', '测试范围', '测试环境', '测试资源', '测试进度'] },
  { key: '03_design', code: '03', name: '测试设计', order: 3, pillar: 'design', pillar_name: '测试设计', categories: ['测试场景', '测试点', '测试数据', '测试矩阵', '测试设计文档', '测试覆盖率'] },
  { key: '04_cases', code: '04', name: '测试用例', order: 4, pillar: 'design', pillar_name: '测试设计', categories: ['功能测试用例', '接口测试用例', 'UI测试用例', '异常测试用例', '边界测试用例', '回归测试用例'] },
  { key: '05_scripts', code: '05', name: '测试脚本', order: 5, pillar: 'design', pillar_name: '测试设计', categories: ['UI自动化脚本', 'API自动化脚本', '数据库脚本', 'Playwright脚本', '辅助测试脚本', '自动化测试脚本'] },
  { key: '06_execution', code: '06', name: '测试执行', order: 6, pillar: 'execute', pillar_name: '测试执行', categories: ['测试执行记录', '执行结果', '测试截图', '测试视频', '执行日志', '测试数据', '失败分析'] },
  { key: '07_defect', code: '07', name: '缺陷管理', order: 7, pillar: 'execute', pillar_name: '测试执行', categories: ['缺陷记录', '缺陷复现步骤', '缺陷截图', '缺陷视频', '缺陷日志', '缺陷修复记录', '缺陷验证'] },
  { key: '08_regression', code: '08', name: '回归测试', order: 8, pillar: 'execute', pillar_name: '测试执行', categories: ['回归测试记录', '回归测试用例', '回归执行结果', '缺陷验证结果'] },
  { key: '09_report', code: '09', name: '测试报告', order: 9, pillar: 'execute', pillar_name: '测试执行', categories: ['测试报告', '测试结果统计', '用例统计', '缺陷统计', '覆盖率', '风险评估', '发布建议'] },
  { key: '10_archive', code: '10', name: '测试归档', order: 10, pillar: 'execute', pillar_name: '测试执行', categories: ['最终测试用例', '最终测试脚本', '最终测试报告', '测试基线', '项目测试资产快照'] },
];

function buildPillars(stages: LifecycleStage[], remote?: LifecyclePillar[]): LifecyclePillar[] {
  if (remote?.length) return remote;
  return PILLARS.map((pillar) => {
    const children = stages.filter((stage) => (stage.pillar || PILLAR_BY_STAGE[stage.key]) === pillar.key);
    return {
      key: pillar.key,
      code: pillar.code,
      name: pillar.name,
      order: Number(pillar.code),
      summary: pillar.summary,
      stage_keys: pillar.stageKeys,
      asset_count: children.reduce((sum, item) => sum + (item.asset_count || 0), 0),
      status: children.some((item) => (item.asset_count || 0) > 0) ? '已有资产' : '待沉淀',
      stages: children,
    };
  });
}

export default function AssetLifecyclePage() {
  const { stage: stageParam } = useParams();
  const navigate = useNavigate();
  const stageKey = stageParam || '';
  const [stages, setStages] = useState<LifecycleStage[]>(FALLBACK_STAGES);
  const [pillars, setPillars] = useState<LifecyclePillar[]>(buildPillars(FALLBACK_STAGES));
  const [items, setItems] = useState<LifecycleAsset[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState<string>();
  const [source, setSource] = useState<string>();
  const [category, setCategory] = useState<string>();
  const [sortField, setSortField] = useState<string>('updated_at');
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<LifecycleAsset | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkTarget, setLinkTarget] = useState<number>();
  const [linkKeyword, setLinkKeyword] = useState('');
  const [linkOptions, setLinkOptions] = useState<{ value: number; label: string }[]>([]);
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();

  const current = stages.find((item) => item.key === stageKey);
  const isFlow = !stageKey;

  const loadStages = useCallback(async () => {
    const data = await fetchLifecycleStages(getCurrentProjectId());
    setStages(data?.stages?.length ? data.stages : FALLBACK_STAGES);
  }, []);

  const loadAssets = useCallback(async () => {
    if (!stageKey) return;
    setLoading(true);
    try {
      const data = await fetchLifecycleAssets({
        stage: stageKey,
        keyword: keyword || undefined,
        status,
        source,
        project_id: getCurrentProjectId() || undefined,
        page,
        page_size: 20,
      });
      let nextItems = data?.items || [];
      if (category) nextItems = nextItems.filter((item: LifecycleAsset) => item.category === category);
      if (sortField === 'name') nextItems = [...nextItems].sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'));
      if (sortField === 'relation_count') nextItems = [...nextItems].sort((a, b) => (b.relation_count || 0) - (a.relation_count || 0));
      setItems(nextItems);
      setTotal(category ? nextItems.length : (data?.total || 0));
    } catch {
      message.error('加载资产失败');
    } finally {
      setLoading(false);
    }
  }, [stageKey, keyword, status, source, category, sortField, page]);

  useEffect(() => {
    loadStages().catch(() => undefined);
    const reload = () => {
      loadStages().catch(() => undefined);
      loadAssets().catch(() => undefined);
    };
    window.addEventListener(PROJECT_CHANGED, reload);
    return () => window.removeEventListener(PROJECT_CHANGED, reload);
  }, [loadStages, loadAssets]);

  useEffect(() => {
    void loadAssets();
  }, [loadAssets]);

  const openDetail = async (id: number) => {
    const data = await getLifecycleAsset(id);
    setDetail(data);
  };

  const createAsset = async (values: any) => {
    const created = await createLifecycleAsset({
      ...values,
      stage: stageKey || values.stage,
      project_id: getCurrentProjectId() || undefined,
    });
    message.success('资产已创建');
    setCreateOpen(false);
    form.resetFields();
    await loadStages();
    await loadAssets();
    if (created?.id) await openDetail(created.id);
  };

  const syncExisting = async () => {
    const data = await syncLifecycleAssets(getCurrentProjectId());
    message.success(`已沉淀 ${data?.sunk || 0} 条已有测试产物`);
    await loadStages();
    await loadAssets();
  };

  const searchLinkTargets = useCallback(async (value?: string) => {
    const data = await fetchLifecycleAssets({
      keyword: value || undefined,
      project_id: getCurrentProjectId() || undefined,
      page: 1,
      page_size: 50,
    });
    setLinkOptions((data?.items || [])
      .filter((item: LifecycleAsset) => item.id !== detail?.id)
      .map((item: LifecycleAsset) => ({
        value: item.id,
        label: `${item.stage_name} · ${item.asset_code} ${item.name}`,
      })));
  }, [detail]);

  const linkCurrent = async () => {
    if (!detail || !linkTarget) return;
    await linkLifecycleAsset(detail.id, linkTarget);
    message.success('已建立关联');
    setLinkOpen(false);
    setLinkTarget(undefined);
    await openDetail(detail.id);
    await loadAssets();
  };

  const saveEdit = async (values: any) => {
    if (!detail) return;
    await updateLifecycleAsset(detail.id, values);
    message.success('资产已更新');
    setEditOpen(false);
    await openDetail(detail.id);
    await loadAssets();
  };

  return (
    <div style={{ display: 'flex', gap: 16, minHeight: 'calc(100vh - 96px)' }}>
      <Card title="测试生命周期" style={{ width: 260, flexShrink: 0 }} size="small">
        <Button
          type={isFlow ? 'primary' : 'text'}
          block
          icon={<PartitionOutlined />}
          style={{ marginBottom: 8, textAlign: 'left' }}
          onClick={() => navigate('/asset/lifecycle')}
        >
          四板块总览
        </Button>
        {pillars.map((pillar) => (
          <div key={pillar.key} style={{ marginBottom: 12 }}>
            <Button
              type="text"
              block
              style={{ textAlign: 'left', fontWeight: 600 }}
              onClick={() => navigate(pillar.key === 'workspace' ? '/workspace' : `/${pillar.key}`)}
            >
              {pillar.code} {pillar.name}
              <Text type="secondary" style={{ float: 'right' }}>{pillar.asset_count || 0}</Text>
            </Button>
            {(pillar.stages || []).map((stage) => (
              <Button
                key={stage.key}
                type={stage.key === stageKey ? 'primary' : 'text'}
                block
                style={{ marginBottom: 4, textAlign: 'left', paddingLeft: 20 }}
                onClick={() => { setPage(1); navigate(`/asset/lifecycle/${stage.key}`); }}
              >
                {stage.name}
                <Text type="secondary" style={{ float: 'right' }}>{stage.asset_count || 0}</Text>
              </Button>
            ))}
          </div>
        ))}
      </Card>

      <div style={{ flex: 1, minWidth: 0 }}>
        {isFlow ? (
          <Card
            title="测试生命周期"
            extra={<Button onClick={() => void syncExisting()}>沉淀已有产物</Button>}
          >
            <Paragraph type="secondary">
              一级目录只有工作空间、项目理解、测试设计和测试执行。原有用例、脚本、缺陷、回归和报告都还在，只是改到对应板块下面。
            </Paragraph>
            <div>
              {pillars.map((pillar, index) => (
                <div key={pillar.key}>
                  <Card
                    size="small"
                    hoverable
                    style={{ marginBottom: 8 }}
                    onClick={() => navigate(pillar.key === 'workspace' ? '/workspace' : `/${pillar.key}`)}
                  >
                    <Space>
                      <Tag color="blue">{pillar.code}</Tag>
                      <Text strong>{pillar.name}</Text>
                      <Tag>{pillar.status || '待沉淀'}</Tag>
                      <Text type="secondary">{pillar.asset_count || 0} 个资产</Text>
                      {pillar.updated_at && <Text type="secondary">最近更新 {pillar.updated_at}</Text>}
                    </Space>
                    <Paragraph type="secondary" style={{ margin: '8px 0 0' }}>{pillar.summary}</Paragraph>
                    <div style={{ marginTop: 8 }}>
                      {(pillar.stages || []).map((stage) => (
                        <Tag
                          key={stage.key}
                          style={{ cursor: 'pointer' }}
                          onClick={(event) => {
                            event.stopPropagation();
                            navigate(`/asset/lifecycle/${stage.key}`);
                          }}
                        >
                          {stage.name} {stage.asset_count || 0}
                        </Tag>
                      ))}
                      {pillar.key === 'workspace' && <Tag>项目 / 环境 / 任务 / 进度</Tag>}
                    </div>
                  </Card>
                  {index < pillars.length - 1 && <div style={{ textAlign: 'center', color: '#999', marginBottom: 8 }}>↓</div>}
                </div>
              ))}
            </div>
          </Card>
        ) : (
          <Card
            title={<Title level={4} style={{ margin: 0 }}>{current ? `${current.code}_${current.name}` : '测试资产'}</Title>}
            extra={
              <Space>
                <Button icon={<ReloadOutlined />} onClick={() => void loadAssets()}>刷新</Button>
                <Button onClick={() => void syncExisting()}>沉淀已有产物</Button>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建资产</Button>
              </Space>
            }
          >
            <Space wrap style={{ marginBottom: 12 }}>
              <Input.Search placeholder="搜索资产" allowClear style={{ width: 220 }} onSearch={(value) => { setKeyword(value); setPage(1); }} />
              <Select allowClear placeholder="状态" style={{ width: 120 }} value={status} onChange={setStatus}
                options={[{ value: 'draft', label: '草稿' }, { value: 'active', label: '已发布' }, { value: 'archived', label: '已归档' }]} />
              <Select allowClear placeholder="创建方式" style={{ width: 140 }} value={source} onChange={setSource}
                options={[{ value: 'ai', label: 'AI生成' }, { value: 'manual', label: '人工创建' }, { value: 'auto', label: '自动生成' }]} />
              <Select allowClear placeholder="类型筛选" style={{ width: 150 }} value={category} onChange={(value) => { setCategory(value); setPage(1); }}
                options={(current?.categories || []).map((item) => ({ value: item, label: item }))} />
              <Select placeholder="排序" style={{ width: 130 }} value={sortField} onChange={setSortField}
                options={[{ value: 'updated_at', label: '按更新时间' }, { value: 'name', label: '按名称' }, { value: 'relation_count', label: '按关联数' }]} />
            </Space>
            <Paragraph type="secondary">{current?.categories.join(' / ')}</Paragraph>
            <Table
              rowKey="id"
              loading={loading}
              dataSource={items}
              pagination={{ current: page, total, pageSize: 20, onChange: setPage }}
              onRow={(row) => ({ onClick: () => { void openDetail(row.id); } })}
              columns={[
                { title: '资产名称', dataIndex: 'name', ellipsis: true },
                { title: '资产类型', dataIndex: 'category', width: 140 },
                { title: '状态', dataIndex: 'status', width: 90, render: (value) => <Tag>{value}</Tag> },
                { title: '所属阶段', dataIndex: 'stage_name', width: 110 },
                { title: '创建方式', dataIndex: 'origin', width: 100 },
                { title: '更新时间', dataIndex: 'updated_at', width: 180 },
                { title: '关联数量', dataIndex: 'relation_count', width: 90 },
              ]}
            />
            {items.length === 0 && !loading && <Empty description="这个阶段还没有资产，可新建或沉淀已有产物" />}
          </Card>
        )}
      </div>

      <Drawer title={detail?.name} width={520} open={!!detail} onClose={() => setDetail(null)}>
        {detail && (
          <div>
            <Paragraph>{detail.content || detail.summary || '暂无内容'}</Paragraph>
            <Card size="small" title="基本信息" style={{ marginBottom: 12 }}>
              <p>编码：{detail.asset_code}</p>
              <p>类型：{detail.category} / {detail.asset_type}</p>
              <p>阶段：{detail.stage_name}</p>
              <p>创建方式：{detail.origin}</p>
              <p>状态：{detail.status} · 版本 v{detail.version}</p>
              <p>可复用：{detail.reusable ? '是' : '否'}</p>
              <p>创建人：{detail.created_by || '-'}</p>
              <p>创建时间：{detail.created_at || '-'}</p>
              <p>标签：{(detail.tags || []).join(', ') || '-'}</p>
              <p>更新时间：{detail.updated_at || '-'}</p>
            </Card>
            <Card size="small" title="关联资产" extra={<Button size="small" onClick={() => { setLinkOpen(true); void searchLinkTargets(); }}>添加关联</Button>}>
              {(['upstream', 'downstream', 'similar', 'defects', 'cases', 'scripts', 'runs'] as const).map((key) => (
                <div key={key} style={{ marginBottom: 8 }}>
                  <Text type="secondary">
                    {{
                      upstream: '来源资产',
                      downstream: '下游资产',
                      similar: '同类资产',
                      defects: '关联缺陷',
                      cases: '关联测试用例',
                      scripts: '关联测试脚本',
                      runs: '关联执行记录',
                    }[key]}
                  </Text>
                  {(detail.relations?.[key] || []).length === 0 ? <div>-</div> : (detail.relations?.[key] || []).map((item) => (
                    <div key={`${key}-${item.id}`}>
                      <Button type="link" onClick={() => void openDetail(item.id)}>{item.name}</Button>
                    </div>
                  ))}
                </div>
              ))}
            </Card>
            <Card size="small" title="版本 / 操作记录" style={{ marginTop: 12 }}>
              <p>v{detail.version} · {detail.origin} · 创建于 {detail.created_at || '-'}</p>
              <p>最近更新 {detail.updated_at || '-'}</p>
            </Card>
            <Space style={{ marginTop: 12 }}>
              <Button onClick={() => {
                editForm.setFieldsValue({ name: detail.name, content: detail.content, category: detail.category });
                setEditOpen(true);
              }}>编辑</Button>
              <Button onClick={() => {
                Modal.confirm({
                  title: '标记为可复用',
                  onOk: async () => {
                    await updateLifecycleAsset(detail.id, { reusable: true, status: 'active' });
                    message.success('已更新');
                    await openDetail(detail.id);
                  },
                });
              }}>发布/复用</Button>
            </Space>
          </div>
        )}
      </Drawer>

      <Modal title="新建资产" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => form.submit()} okText="创建">
        <Form form={form} layout="vertical" onFinish={(values) => void createAsset(values)}>
          {!stageKey && (
            <Form.Item name="stage" label="所属阶段" rules={[{ required: true, message: '请选择阶段' }]}>
              <Select options={stages.map((item) => ({ value: item.key, label: `${item.code}_${item.name}` }))} />
            </Form.Item>
          )}
          <Form.Item name="name" label="资产名称" rules={[{ required: true, message: '请填写名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="category" label="资产类型" rules={[{ required: true, message: '请选择类型' }]}>
            <Select options={(current?.categories || []).map((item) => ({ value: item, label: item }))} />
          </Form.Item>
          <Form.Item name="content" label="资产内容" rules={[{ required: true, message: '请填写内容' }]}>
            <Input.TextArea rows={5} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="编辑资产" open={editOpen} onCancel={() => setEditOpen(false)} onOk={() => editForm.submit()} okText="保存">
        <Form form={editForm} layout="vertical" onFinish={(values) => void saveEdit(values)}>
          <Form.Item name="name" label="资产名称" rules={[{ required: true, message: '请填写名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="category" label="资产类型">
            <Select options={(current?.categories || stages.flatMap((item) => item.categories)).map((item) => ({ value: item, label: item }))} />
          </Form.Item>
          <Form.Item name="content" label="资产内容" rules={[{ required: true, message: '请填写内容' }]}>
            <Input.TextArea rows={6} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="关联资产" open={linkOpen} onCancel={() => setLinkOpen(false)} onOk={() => void linkCurrent()} okText="关联">
        <Select
          showSearch
          style={{ width: '100%' }}
          placeholder="搜索并选择任意阶段的资产"
          options={linkOptions}
          value={linkTarget}
          filterOption={false}
          onSearch={(value) => { setLinkKeyword(value); void searchLinkTargets(value); }}
          onChange={setLinkTarget}
        />
      </Modal>
    </div>
  );
}
