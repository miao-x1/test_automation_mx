/**
 * AI上下文展示组件
 *
 * 展示AI生成脚本时使用了哪些上下文数据：
 *   - 业务数据（来自MySQL）
 *   - 知识参考（来自Milvus）
 *   - 业务关系（来自Neo4j）
 */
import { useState } from 'react';
import {
  Card,
  Tabs,
  Table,
  Tag,
  Empty,
  Spin,
  Button,
  Descriptions,
  Typography,
  Space,
  Alert,
  Input,
} from 'antd';
import {
  DatabaseOutlined,
  CloudOutlined,
  ApartmentOutlined,
  SearchOutlined,
} from '@ant-design/icons';

import {
  getContextPreview,
  type ContextPreview,
  type RetrievalPlan,
} from '../../services/contextService';

const { Text } = Typography;

interface AIContextTabProps {
  taskId?: string;
}

export default function AIContextTab({ taskId }: AIContextTabProps) {
  const [loading, setLoading] = useState(false);
  const [contextData, setContextData] = useState<ContextPreview | null>(null);
  const [inputTaskId, setInputTaskId] = useState(taskId || '');

  // 加载上下文数据
  const handleLoad = async () => {
    if (!inputTaskId.trim()) return;
    setLoading(true);
    try {
      const data = await getContextPreview(inputTaskId);
      setContextData(data);
    } catch (err: any) {
      console.error('加载上下文失败:', err);
    } finally {
      setLoading(false);
    }
  };

  // 渲染路由计划
  const renderPlan = (plan: RetrievalPlan) => (
    <Descriptions column={3} size="small" bordered>
      <Descriptions.Item label="任务类型" span={3}>
        <Tag color="cyan">{plan.task_type}</Tag>
      </Descriptions.Item>
      <Descriptions.Item label="MySQL表" span={3}>
        {plan.mysql.tables.map(t => <Tag key={t} color="blue">{t}</Tag>)}
      </Descriptions.Item>
      <Descriptions.Item label="Milvus集合" span={3}>
        {plan.milvus.collections.map(c => <Tag key={c} color="purple">{c}</Tag>)}
      </Descriptions.Item>
      <Descriptions.Item label="Milvus查询" span={3}>
        {plan.milvus.queries.map((q, i) => (
          <Tag key={i} color="purple">{q}</Tag>
        ))}
      </Descriptions.Item>
      <Descriptions.Item label="Neo4j标签" span={3}>
        {plan.neo4j.node_labels.length > 0
          ? plan.neo4j.node_labels.map(l => <Tag key={l} color="green">{l}</Tag>)
          : <Text type="secondary">跳过</Text>}
      </Descriptions.Item>
      <Descriptions.Item label="路由理由" span={3}>
        <Text type="secondary">{plan.reason}</Text>
      </Descriptions.Item>
    </Descriptions>
  );

  // 渲染MySQL业务数据
  const renderMysqlData = (data: Record<string, any>) => {
    if (!data || Object.keys(data).length === 0) {
      return <Empty description="无MySQL数据" />;
    }
    return (
      <div>
        {Object.entries(data).map(([table, value]: [string, any]) => (
          <Card key={table} size="small" title={`${table} (${value?.count || 0}条)`} style={{ marginBottom: 8 }}>
            {value?.data && Array.isArray(value.data) ? (
              <Table
                size="small"
                dataSource={value.data.map((row: any, i: number) => ({ ...row, key: i }))}
                columns={Object.keys(value.data[0] || {}).slice(0, 5).map((col: string) => ({
                  title: col,
                  dataIndex: col,
                  key: col,
                  ellipsis: true,
                }))}
                pagination={false}
                scroll={{ x: true }}
              />
            ) : (
              <Text type="secondary">{JSON.stringify(value)}</Text>
            )}
          </Card>
        ))}
      </div>
    );
  };

  // 渲染Milvus向量结果
  const renderMilvusData = (data: Record<string, any>) => {
    if (!data || Object.keys(data).length === 0) {
      return <Empty description="无Milvus数据" />;
    }
    return (
      <div>
        {Object.entries(data).map(([collection, value]: [string, any]) => (
          <Card
            key={collection}
            size="small"
            title={`${collection} (${value?.count || 0}条)`}
            style={{ marginBottom: 8 }}
          >
            {value?.references && Array.isArray(value.references) ? (
              <div>
                {value.references.map((ref: any, i: number) => (
                  <div key={i} style={{ marginBottom: 8, padding: 8, background: '#fafafa', borderRadius: 4 }}>
                    <Space>
                      <Tag color="purple">相似度: {(ref.score * 100).toFixed(0)}%</Tag>
                      {ref.source_type && <Tag>{ref.source_type}</Tag>}
                      {ref.entity_type && <Tag>{ref.entity_type}</Tag>}
                    </Space>
                    <Text style={{ display: 'block', marginTop: 4 }}>
                      {ref.text?.substring(0, 200)}{ref.text?.length > 200 ? '...' : ''}
                    </Text>
                  </div>
                ))}
              </div>
            ) : (
              <Text type="secondary">{JSON.stringify(value)}</Text>
            )}
          </Card>
        ))}
      </div>
    );
  };

  // 渲染Neo4j图数据
  const renderNeo4jData = (data: Record<string, any>) => {
    if (!data || Object.keys(data).length === 0) {
      return <Empty description="无Neo4j数据" />;
    }
    return (
      <div>
        {data.nodes && (
          <Card size="small" title={`节点 (${data.nodes.count || 0}个)`} style={{ marginBottom: 8 }}>
            <div style={{ maxHeight: 200, overflow: 'auto' }}>
              {(data.nodes.data || []).map((node: any, i: number) => (
                <Tag key={i} color="green" style={{ marginBottom: 4 }}>
                  {(node.labels || []).join(':')} | {node.name || node.title || 'unnamed'}
                </Tag>
              ))}
            </div>
          </Card>
        )}
        {data.relationships && (
          <Card size="small" title={`关系 (${data.relationships.count || 0}条)`} style={{ marginBottom: 8 }}>
            <div style={{ maxHeight: 200, overflow: 'auto' }}>
              {(data.relationships.data || []).map((rel: any, i: number) => (
                <div key={i} style={{ marginBottom: 4 }}>
                  <Text>{rel.start_node?.name || rel.start_node?.title || '?'}</Text>
                  <Text type="success"> →[{rel.type}]→ </Text>
                  <Text>{rel.end_node?.name || rel.end_node?.title || '?'}</Text>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    );
  };

  return (
    <div style={{ padding: 16 }}>
      {/* 搜索栏 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <Input
            placeholder="输入Task ID"
            value={inputTaskId}
            onChange={e => setInputTaskId(e.target.value)}
            style={{ width: 300 }}
            onPressEnter={handleLoad}
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleLoad} loading={loading}>
            查看上下文
          </Button>
        </Space>
      </Card>

      {loading ? (
        <div style={{ textAlign: 'center', paddingTop: 50 }}>
          <Spin size="large" />
        </div>
      ) : contextData ? (
        <>
          {/* 摘要 */}
          <Alert
            type="info"
            showIcon
            message={`AI上下文来源: ${contextData.sources.join(' + ') || '无'}`}
            description={
              <Space direction="vertical" size={0}>
                <Text>{contextData.summary}</Text>
                <Text type="secondary">耗时: {contextData.duration.toFixed(3)}秒</Text>
              </Space>
            }
            style={{ marginBottom: 16 }}
          />

          {/* 路由计划 */}
          <Card
            size="small"
            title={<span><SearchOutlined /> 路由计划</span>}
            style={{ marginBottom: 16 }}
          >
            {renderPlan(contextData.plan)}
          </Card>

          {/* 三库数据展示 */}
          <Tabs
            items={[
              {
                key: 'mysql',
                label: (
                  <span>
                    <DatabaseOutlined /> 业务数据 (MySQL)
                    {contextData.sources.includes('MySQL') && <Tag color="blue" style={{ marginLeft: 4 }}>已使用</Tag>}
                  </span>
                ),
                children: renderMysqlData(contextData.mysql_data),
              },
              {
                key: 'milvus',
                label: (
                  <span>
                    <CloudOutlined /> 知识参考 (Milvus)
                    {contextData.sources.includes('Milvus') && <Tag color="purple" style={{ marginLeft: 4 }}>已使用</Tag>}
                  </span>
                ),
                children: renderMilvusData(contextData.vector_results),
              },
              {
                key: 'neo4j',
                label: (
                  <span>
                    <ApartmentOutlined /> 业务关系 (Neo4j)
                    {contextData.sources.includes('Neo4j') && <Tag color="green" style={{ marginLeft: 4 }}>已使用</Tag>}
                  </span>
                ),
                children: renderNeo4jData(contextData.graph_results),
              },
            ]}
          />
        </>
      ) : (
        <Empty description="请输入Task ID查看AI使用的上下文" />
      )}
    </div>
  );
}
