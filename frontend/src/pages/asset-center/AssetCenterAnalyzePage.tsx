/**
 * 测试资产中心 - 资产分析页 (Agent 业务流入口)
 *
 * 路由: /asset/center/analyze
 *
 * 业务流:
 *   用户输入需求 → AssetSearchAgent → AssetReuseAgent → AssetOptimizationAgent → 优化方案
 *
 * 功能:
 *   1. 顶部需求输入 + 高级选项(资产类型 / 模块 / 标签 / 限制 / 向量/关系开关)
 *   2. 完整流程执行(搜索 → 复用评估 → 方案优化)
 *   3. 步骤进度条(显示每步耗时和状态)
 *   4. 三类结果展示:
 *      - 搜索结果(命中原因 + 三源得分)
 *      - 复用决策(建议 + 缺失资产 + 摘要)
 *      - 优化方案(执行顺序 + 质量评分 + 摘要)
 *   5. Agent 健康检查
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Input,
  Button,
  Space,
  message,
  Typography,
  Tag,
  Collapse,
  Switch,
  Select,
  InputNumber,
  Steps,
  Alert,
  Empty,
  Statistic,
  Row,
  Col,
  Divider,
  Tooltip,
  Progress,
  List,
} from 'antd';
import {
  ThunderboltOutlined,
  ReloadOutlined,
  SearchOutlined,
  CheckCircleOutlined,
  BulbOutlined,
  HeartOutlined,
  ClockCircleOutlined,
  ApiOutlined,
  ApartmentOutlined,
  DatabaseOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import {
  analyzeRequirement,
  agentHealthCheck,
  type AnalyzeInput,
  type AnalyzeResult,
  type AgentHealthStatus,
  type SearchHitItem,
  type ReuseDecision,
  type ReuseSuggestionItem,
} from '@/services/assetCenter';

const { Title, Paragraph, Text } = Typography;
const { TextArea } = Input;

// 资产类型中文名
const ASSET_TYPE_TEXT: Record<string, string> = {
  api_endpoint: 'API 接口',
  ui_element: 'UI 元素',
  test_case: '测试用例',
  test_asset: '测试资产',
  script: '测试脚本',
  test_data: '测试数据',
  test_report: '测试报告',
  requirement: '需求',
};

// 建议颜色
const SUGGESTION_COLOR: Record<string, string> = {
  reuse: 'green',
  adapt: 'orange',
  skip: 'default',
};

const SUGGESTION_TEXT: Record<string, string> = {
  reuse: '直接复用',
  adapt: '需改造',
  skip: '跳过',
};

// 命中来源颜色
const SOURCE_COLOR: Record<string, string> = {
  mysql: 'blue',
  milvus: 'purple',
  neo4j: 'green',
};

export default function AssetCenterAnalyzePage() {
  // 输入
  const [requirement, setRequirement] = useState('');
  const [assetTypes, setAssetTypes] = useState<string[]>([]);
  const [module, setModule] = useState<string>('');
  const [tags, setTags] = useState<string[]>([]);
  const [limit, setLimit] = useState(10);
  const [useVector, setUseVector] = useState(true);
  const [useRelation, setUseRelation] = useState(true);

  // 执行状态
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<AnalyzeResult | null>(null);

  // 健康检查
  const [health, setHealth] = useState<AgentHealthStatus | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);

  // 健康检查
  const fetchHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const res = await agentHealthCheck();
      // 解包 {code, data: {status, agents}} 信封格式
      setHealth((res as any)?.data ?? res);
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || 'Agent 服务健康检查失败');
    } finally {
      setHealthLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  // 执行完整分析
  const handleAnalyze = async () => {
    if (!requirement.trim()) {
      message.warning('请输入测试需求');
      return;
    }

    setAnalyzing(true);
    setResult(null);
    try {
      const input: AnalyzeInput = {
        requirement: requirement.trim(),
        asset_types: assetTypes.length ? assetTypes : undefined,
        module: module.trim() || undefined,
        tags: tags.length ? tags : undefined,
        limit,
        use_vector: useVector,
        use_relation: useRelation,
      };

      const res = await analyzeRequirement(input);
      // 解包 {code, data: {...}} 信封格式
      const result = (res as any)?.data ?? res;
      setResult(result);

      if (result.status === 'success') {
        message.success(`分析完成, 耗时 ${result.elapsed_ms}ms`);
      } else {
        message.warning(`分析完成 (有错误), 耗时 ${result.elapsed_ms}ms`);
      }
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '分析失败');
    } finally {
      setAnalyzing(false);
    }
  };

  // 步骤展示
  const stepsData = result?.steps?.map(s => {
    const total = typeof s.total === 'number' ? s.total : undefined;
    const canReuse = typeof s.can_reuse === 'boolean' ? s.can_reuse : undefined;
    const qualityScore = typeof s.quality_score === 'number' ? s.quality_score : undefined;
    const errorMsg = typeof s.error === 'string' ? s.error : undefined;
    const stepStatus: 'finish' | 'error' | 'process' =
      s.status === 'success' ? 'finish' : s.status === 'error' ? 'error' : 'process';
    return {
      title: s.step === 'search' ? '资产搜索' : s.step === 'reuse' ? '复用评估' : '方案优化',
      description: (
        <Space direction="vertical" size={0}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            <ClockCircleOutlined /> {s.duration_ms}ms · 状态: {s.status}
          </Text>
          {s.step === 'search' && total !== undefined && (
            <Text style={{ fontSize: 12 }}>找到 {total} 条结果</Text>
          )}
          {s.step === 'reuse' && canReuse !== undefined && (
            <Text style={{ fontSize: 12 }}>建议复用: {canReuse ? '是' : '否'}</Text>
          )}
          {s.step === 'optimize' && qualityScore !== undefined && (
            <Text style={{ fontSize: 12 }}>质量分: {qualityScore}</Text>
          )}
          {errorMsg && <Text type="danger" style={{ fontSize: 12 }}>{errorMsg}</Text>}
        </Space>
      ),
      status: stepStatus,
    };
  }) || [];

  // 提取搜索结果 (兼容两种返回格式)
  const searchHits: SearchHitItem[] = (() => {
    if (!result?.search_results) return [];
    if (Array.isArray(result.search_results)) {
      return result.search_results as SearchHitItem[];
    }
    // 字典格式 (旧版本)
    return [];
  })();

  // 复用决策
  const reuseDecision: ReuseDecision | undefined = result?.reuse_decision;

  // 优化方案
  const optimizedPlan = result?.optimized_plan;

  return (
    <div>
      {/* 顶部: 需求输入 + 高级选项 */}
      <Card
        title={
          <Space>
            <RobotOutlined style={{ color: '#1677ff' }} />
            <Title level={4} style={{ margin: 0 }}>AI 资产分析</Title>
          </Space>
        }
        extra={
          <Space>
            <Tag color={health?.status === 'healthy' ? 'green' : 'orange'}>
              Agent 服务: {health?.status || '未知'}
            </Tag>
            <Button size="small" icon={<ReloadOutlined />} loading={healthLoading} onClick={fetchHealth}>
              检查
            </Button>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Paragraph type="secondary">
          输入自然语言测试需求, AI 将自动分析已有资产、评估复用潜力、生成优化测试方案。
        </Paragraph>

        <TextArea
          value={requirement}
          onChange={(e) => setRequirement(e.target.value)}
          rows={3}
          placeholder="例: 测试登录功能, 包括账号密码登录、短信验证码登录、SSO 第三方登录"
          maxLength={500}
          showCount
        />

        <Collapse
          ghost
          style={{ marginTop: 8 }}
          items={[{
            key: 'advanced',
            label: '高级选项',
            children: (
              <Space wrap size="middle">
                <div>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                    资产类型 (空=全部)
                  </Text>
                  <Select
                    mode="multiple"
                    style={{ width: 280 }}
                    placeholder="限定资产类型"
                    value={assetTypes}
                    onChange={setAssetTypes}
                    allowClear
                    options={Object.entries(ASSET_TYPE_TEXT).map(([value, label]) => ({ value, label }))}
                  />
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                    模块
                  </Text>
                  <Input
                    style={{ width: 160 }}
                    placeholder="例: 用户中心"
                    value={module}
                    onChange={(e) => setModule(e.target.value)}
                    allowClear
                  />
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                    标签
                  </Text>
                  <Select
                    mode="tags"
                    style={{ width: 200 }}
                    placeholder="输入标签回车"
                    value={tags}
                    onChange={setTags}
                    tokenSeparators={[',']}
                  />
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                    结果上限
                  </Text>
                  <InputNumber
                    min={1}
                    max={50}
                    value={limit}
                    onChange={(v) => setLimit(v ?? 10)}
                    style={{ width: 100 }}
                  />
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                    Milvus 向量召回
                  </Text>
                  <Switch checked={useVector} onChange={setUseVector} />
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                    Neo4j 关系扩展
                  </Text>
                  <Switch checked={useRelation} onChange={setUseRelation} />
                </div>
              </Space>
            ),
          }]}
        />

        <Divider style={{ margin: '12px 0' }} />

        <Space>
          <Button
            type="primary"
            size="large"
            icon={<ThunderboltOutlined />}
            loading={analyzing}
            onClick={handleAnalyze}
            disabled={!requirement.trim()}
          >
            开始分析
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            完整流程: 搜索 → 复用评估 → 方案优化
          </Text>
        </Space>

        {/* Agent 列表 */}
        {health && (
          <div style={{ marginTop: 12 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>已注册 Agent:</Text>
            <Space style={{ marginLeft: 8 }}>
              {health.agents.map(a => (
                <Tooltip key={a.name} title={`类型: ${a.type}, 状态: ${a.enabled ? '启用' : '禁用'}`}>
                  <Tag color={a.type === 'llm' ? 'purple' : 'blue'} style={{ fontFamily: 'monospace', fontSize: 11 }}>
                    {a.name}
                  </Tag>
                </Tooltip>
              ))}
            </Space>
          </div>
        )}
      </Card>

      {/* 结果展示 */}
      {result && (
        <>
          {/* 顶部总览 */}
          <Card style={{ marginBottom: 16 }}>
            <Row gutter={16}>
              <Col span={4}>
                <Statistic
                  title="总耗时"
                  value={result.elapsed_ms}
                  suffix="ms"
                  prefix={<ClockCircleOutlined />}
                />
              </Col>
              <Col span={4}>
                <Statistic
                  title="搜索结果"
                  value={searchHits.length}
                  prefix={<SearchOutlined />}
                />
              </Col>
              <Col span={4}>
                <Statistic
                  title="复用建议"
                  value={reuseDecision?.suggestions?.length || 0}
                  prefix={<HeartOutlined />}
                />
              </Col>
              <Col span={4}>
                <Statistic
                  title="缺失资产"
                  value={reuseDecision?.missing_assets?.length || 0}
                  valueStyle={{ color: '#fa8c16' }}
                  prefix={<Alert type="warning" message="" banner style={{ border: 'none', background: 'transparent' }} />}
                />
              </Col>
              <Col span={4}>
                <Statistic
                  title="质量评分"
                  value={optimizedPlan?.quality_score ?? 0}
                  suffix="/100"
                  valueStyle={{ color: '#1677ff' }}
                  prefix={<BulbOutlined />}
                />
              </Col>
              <Col span={4}>
                <Statistic
                  title="执行状态"
                  value={result.status === 'success' ? '成功' : '失败'}
                  valueStyle={{ color: result.status === 'success' ? '#52c41a' : '#ff4d4f' }}
                  prefix={<CheckCircleOutlined />}
                />
              </Col>
            </Row>
          </Card>

          {/* 步骤进度 */}
          {stepsData.length > 0 && (
            <Card title="执行步骤" style={{ marginBottom: 16 }}>
              <Steps
                current={stepsData.length - 1}
                size="small"
                direction="vertical"
                items={stepsData}
              />
            </Card>
          )}

          {/* 搜索结果 */}
          <Card
            title={
              <Space>
                <SearchOutlined />
                <span>搜索结果</span>
                <Tag color="blue">{searchHits.length}</Tag>
              </Space>
            }
            style={{ marginBottom: 16 }}
          >
            {searchHits.length > 0 ? (
              <List
                dataSource={searchHits}
                renderItem={(hit) => (
                  <List.Item>
                    <div style={{ width: '100%' }}>
                      <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                        <Space>
                          <Tag color="blue">{ASSET_TYPE_TEXT[hit.asset_type] || hit.asset_type}</Tag>
                          <Text strong>{hit.name}</Text>
                          <Text type="secondary" style={{ fontFamily: 'monospace', fontSize: 12 }}>
                            {hit.asset_code}
                          </Text>
                        </Space>
                        <Space>
                          <Tooltip title={`MySQL: ${hit.mysql_score?.toFixed(2) || 0}`}>
                            <Tag color="blue">MySQL: {(hit.mysql_score ?? 0).toFixed(2)}</Tag>
                          </Tooltip>
                          {hit.vector_score !== null && hit.vector_score !== undefined && (
                            <Tooltip title="Milvus 向量相似度">
                              <Tag color="purple">向量: {hit.vector_score.toFixed(2)}</Tag>
                            </Tooltip>
                          )}
                          {hit.relation_score !== null && hit.relation_score !== undefined && (
                            <Tooltip title="Neo4j 关系关联度">
                              <Tag color="green">关系: {hit.relation_score.toFixed(2)}</Tag>
                            </Tooltip>
                          )}
                          <Tag color="gold">综合: {hit.final_score.toFixed(2)}</Tag>
                        </Space>
                      </Space>
                      {hit.summary && (
                        <Paragraph style={{ margin: '4px 0 0 0', fontSize: 12, color: '#8c8c8c' }}>
                          {hit.summary}
                        </Paragraph>
                      )}
                      {hit.match_reasons && hit.match_reasons.length > 0 && (
                        <div style={{ marginTop: 4 }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>命中原因:</Text>
                          <Space size={4} wrap style={{ marginLeft: 8 }}>
                            {hit.match_reasons.map((r, i) => (
                              <Tooltip key={i} title={`${r.source} 得分: ${r.score?.toFixed(2)}${r.detail ? ' · ' + r.detail : ''}`}>
                                <Tag color={SOURCE_COLOR[r.source] || 'default'} style={{ fontSize: 11 }}>
                                  {r.source}{r.field ? `.${r.field}` : ''}: {r.score?.toFixed(2)}
                                </Tag>
                              </Tooltip>
                            ))}
                          </Space>
                        </div>
                      )}
                    </div>
                  </List.Item>
                )}
              />
            ) : (
              <Empty description="未找到匹配资产" />
            )}
          </Card>

          {/* 复用决策 */}
          {reuseDecision && (
            <Card
              title={
                <Space>
                  <HeartOutlined />
                  <span>复用决策</span>
                  <Tag color={reuseDecision.can_reuse ? 'green' : 'orange'}>
                    {reuseDecision.can_reuse ? '建议复用' : '需新建为主'}
                  </Tag>
                  {reuseDecision.degraded && <Tag color="volcano">降级模式</Tag>}
                </Space>
              }
              style={{ marginBottom: 16 }}
            >
              <Paragraph>{reuseDecision.summary}</Paragraph>

              {reuseDecision.missing_assets && reuseDecision.missing_assets.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message="缺失资产类型(需新建)"
                  description={
                    <Space wrap>
                      {reuseDecision.missing_assets.map(a => (
                        <Tag key={a} color="orange">{ASSET_TYPE_TEXT[a] || a}</Tag>
                      ))}
                    </Space>
                  }
                  style={{ marginBottom: 12 }}
                />
              )}

              {reuseDecision.suggestions && reuseDecision.suggestions.length > 0 && (
                <List
                  dataSource={reuseDecision.suggestions}
                  renderItem={(s: ReuseSuggestionItem) => (
                    <List.Item>
                      <div style={{ width: '100%' }}>
                        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                          <Space>
                            <Tag color={ASSET_TYPE_TEXT[s.asset_type] ? 'blue' : 'default'}>
                              {ASSET_TYPE_TEXT[s.asset_type] || s.asset_type}
                            </Tag>
                            <Text strong>{s.name}</Text>
                            <Tag color={SUGGESTION_COLOR[s.suggestion] || 'default'}>
                              {SUGGESTION_TEXT[s.suggestion] || s.suggestion}
                            </Tag>
                          </Space>
                          <Tag color="gold">复用分: {s.reuse_score.toFixed(2)}</Tag>
                        </Space>
                        <Paragraph style={{ margin: '4px 0', fontSize: 12, color: '#8c8c8c' }}>
                          {s.reason}
                        </Paragraph>
                        <Space size="small" wrap>
                          <Tag color="blue">需求覆盖: {s.coverage.toFixed(2)}</Tag>
                          <Tag color="blue">字段匹配: {s.field_match.toFixed(2)}</Tag>
                          <Tag color="blue">质量: {s.quality.toFixed(1)}</Tag>
                          <Tag color="blue">时效: {s.recency.toFixed(2)}</Tag>
                          <Tag color="blue">历史复用: {s.history.toFixed(2)}</Tag>
                        </Space>
                      </div>
                    </List.Item>
                  )}
                />
              )}
            </Card>
          )}

          {/* 优化方案 */}
          {optimizedPlan && (
            <Card
              title={
                <Space>
                  <BulbOutlined />
                  <span>优化测试方案</span>
                  <Tag color="green">质量分: {optimizedPlan.quality_score}</Tag>
                </Space>
              }
            >
              <Paragraph>{optimizedPlan.summary}</Paragraph>

              <Row gutter={16} style={{ marginBottom: 12 }}>
                <Col span={8}>
                  <Card size="small">
                    <Statistic
                      title="直接复用资产"
                      value={optimizedPlan.reuse_assets?.length || 0}
                      valueStyle={{ color: '#52c41a' }}
                      prefix={<CheckCircleOutlined />}
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small">
                    <Statistic
                      title="需改造资产"
                      value={optimizedPlan.adapt_assets?.length || 0}
                      valueStyle={{ color: '#faad14' }}
                      prefix={<ApiOutlined />}
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small">
                    <Statistic
                      title="需新建资产"
                      value={optimizedPlan.new_assets?.length || 0}
                      valueStyle={{ color: '#ff4d4f' }}
                      prefix={<DatabaseOutlined />}
                    />
                  </Card>
                </Col>
              </Row>

              {optimizedPlan.execution_order && optimizedPlan.execution_order.length > 0 && (
                <>
                  <Divider orientation="left" plain>
                    执行顺序
                  </Divider>
                  <Space wrap>
                    {optimizedPlan.execution_order.map((step, i) => (
                      <Tag key={i} color="processing" style={{ fontSize: 13, padding: '4px 12px' }}>
                        {i + 1}. {step}
                      </Tag>
                    ))}
                  </Space>
                </>
              )}

              {optimizedPlan.new_assets && optimizedPlan.new_assets.length > 0 && (
                <>
                  <Divider orientation="left" plain>
                    新建资产清单
                  </Divider>
                  <List
                    size="small"
                    dataSource={optimizedPlan.new_assets}
                    renderItem={(item, i) => (
                      <List.Item>
                        <Space>
                          <Tag color="orange">#{i + 1}</Tag>
                          <pre style={{ margin: 0, fontSize: 12 }}>
                            {JSON.stringify(item, null, 2)}
                          </pre>
                        </Space>
                      </List.Item>
                    )}
                  />
                </>
              )}

              <Divider orientation="left" plain>
                <Space>
                  <ApartmentOutlined />
                  <span>建议关系图</span>
                </Space>
              </Divider>
              <Progress
                percent={optimizedPlan.quality_score}
                status={optimizedPlan.quality_score >= 80 ? 'success' : optimizedPlan.quality_score >= 60 ? 'active' : 'exception'}
                format={(p) => `质量评分 ${p}/100`}
              />
            </Card>
          )}

          {result.error && (
            <Alert
              type="error"
              showIcon
              message="分析错误"
              description={result.error}
              style={{ marginTop: 16 }}
            />
          )}
        </>
      )}

      {!result && !analyzing && (
        <Card>
          <Empty
            description={
              <span>
                输入测试需求, 点击「开始分析」
                <br />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Agent 链: AssetSearchAgent → AssetReuseAgent → AssetOptimizationAgent
                </Text>
              </span>
            }
          />
        </Card>
      )}
    </div>
  );
}
