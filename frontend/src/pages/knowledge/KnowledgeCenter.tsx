/**
 * Knowledge Center - 知识中心页面
 *
 * 功能模块：
 *  1. 总览统计 - MySQL/Milvus/Neo4j 三库状态
 *  2. 集合管理 - 向量集合列表/详情/清空
 *  3. 文档管理 - 文档列表/详情/删除
 *  4. Chunk查看 - 分片列表/详情
 *  5. Embedding状态 - 向量化进度检查
 *  6. Graph查看 - Neo4j图谱节点/关系
 *  7. 重建操作 - 重建Embedding/重新分块/重新索引
 *  8. 搜索测试 - 全文检索/语义检索/混合检索
 */
import { useState, useCallback, useEffect } from 'react';
import {
  Card, Table, Button, Space, Input, Tabs, Tag, Statistic, Row, Col,
  Modal, Descriptions, message, Popconfirm, Progress, Empty, Spin,
  Form, Select, InputNumber, Typography, Tooltip, Badge,
  Upload, Alert, Divider,
} from 'antd';
import {
  DatabaseOutlined, FileTextOutlined, ClusterOutlined, SearchOutlined,
  ReloadOutlined, DeleteOutlined, EyeOutlined, BuildOutlined,
  ThunderboltOutlined, ApartmentOutlined, BarChartOutlined,
  BlockOutlined, NodeIndexOutlined, FileSearchOutlined,
  CloudUploadOutlined, ApiOutlined,
} from '@ant-design/icons';
import { PageHeader, StatusTag } from '../../components/UI';
import * as kcApi from '../../services/knowledgeCenter';

const { Text, Paragraph } = Typography;
const { TabPane } = Tabs;

// ===== 类型定义 =====
interface CollectionInfo {
  entity_type: string;
  collection_name: string;
  available: boolean;
  row_count: number;
  error?: string;
}

interface DocumentInfo {
  id: number;
  project_id: string;
  source_type: string;
  file_path: string;
  source_url: string;
  raw_text: string;
  status: string;
  error_message: string;
  chunk_count: number;
  version: number;
  created_at: string;
  indexed_at: string;
}

interface ChunkInfo {
  id: number;
  knowledge_source_id: number;
  milvus_id: number;
  chunk_type: string;
  text: string;
  metadata: any;
  created_at: string;
}

interface SearchResult {
  chunk_id?: number;
  source_id?: string;
  source_type?: string;
  chunk_type?: string;
  text: string;
  score: number;
  entity_type?: string;
  hybrid_score?: number;
  search_type?: string;
}

// ===== 主组件 =====
export default function KnowledgeCenter() {
  const [activeTab, setActiveTab] = useState('overview');

  return (
    <div>
      <PageHeader
        title="知识中心"
        subtitle="统一管理知识库：集合、文档、分片、向量、图谱、搜索测试"
        icon={<DatabaseOutlined />}
      />

      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} type="card" size="large">
          <TabPane
            tab={<span><CloudUploadOutlined /> 知识导入</span>}
            key="import"
          >
            <KnowledgeImportTab />
          </TabPane>

          <TabPane
            tab={<span><BarChartOutlined /> 总览统计</span>}
            key="overview"
          >
            <OverviewTab />
          </TabPane>

          <TabPane
            tab={<span><ClusterOutlined /> 集合管理</span>}
            key="collections"
          >
            <CollectionsTab />
          </TabPane>

          <TabPane
            tab={<span><FileTextOutlined /> 文档管理</span>}
            key="documents"
          >
            <DocumentsTab />
          </TabPane>

          <TabPane
            tab={<span><BlockOutlined /> Chunk查看</span>}
            key="chunks"
          >
            <ChunksTab />
          </TabPane>

          <TabPane
            tab={<span><NodeIndexOutlined /> Embedding状态</span>}
            key="embedding"
          >
            <EmbeddingStatusTab />
          </TabPane>

          <TabPane
            tab={<span><ApartmentOutlined /> Graph查看</span>}
            key="graph"
          >
            <GraphTab />
          </TabPane>

          <TabPane
            tab={<span><ThunderboltOutlined /> 搜索测试</span>}
            key="search"
          >
            <SearchTestTab />
          </TabPane>

          <TabPane
            tab={<span><ApiOutlined /> AI检索配置</span>}
            key="ai-config"
          >
            <AIConfigTab />
          </TabPane>
        </Tabs>
      </Card>
    </div>
  );
}

// ===== 1. 总览统计 =====
function OverviewTab() {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const fetchStats = useCallback(async () => {
    setLoading(true);
    try {
      const res = await kcApi.getCenterStats() as any;
      const data = res?.data || res;
      setStats(data);
    } catch (e) {
      console.error(e);
      message.error('加载统计数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStats(); }, [fetchStats]);

  if (loading) return <Spin tip="加载中..." />;
  if (!stats) return <Empty description="暂无数据" />;

  const mysql = stats.mysql || {};
  const milvus = stats.milvus || {};
  const neo4j = stats.neo4j || {};

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col span={8}>
          <Card title="MySQL" size="small" extra={<Badge status={mysql.total_sources > 0 ? 'success' : 'default'} />}>
            <Row gutter={[8, 8]}>
              <Col span={12}>
                <Statistic title="文档总数" value={mysql.total_sources || 0} />
              </Col>
              <Col span={12}>
                <Statistic title="分片总数" value={mysql.total_chunks || 0} />
              </Col>
            </Row>
            {mysql.by_type && Object.keys(mysql.by_type).length > 0 && (
              <div style={{ marginTop: 12 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>按类型：</Text>
                <div style={{ marginTop: 4 }}>
                  {Object.entries(mysql.by_type).map(([k, v]: any) => (
                    <Tag key={k} style={{ marginBottom: 4 }}>{k}: {v}</Tag>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </Col>

        <Col span={8}>
          <Card title="Milvus" size="small" extra={<Badge status={milvus.available ? 'success' : 'error'} text={milvus.available ? '可用' : '不可用'} />}>
            {milvus.available ? (
              <Row gutter={[8, 8]}>
                {(milvus.collections || []).map((c: any) => (
                  <Col span={12} key={c.entity_type}>
                    <Statistic title={c.entity_type} value={c.row_count || 0} suffix="条" />
                  </Col>
                ))}
              </Row>
            ) : (
              <Empty description={milvus.error || 'Milvus不可用'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>

        <Col span={8}>
          <Card title="Neo4j" size="small" extra={<Badge status={neo4j.available !== false ? 'success' : 'error'} text={neo4j.available !== false ? '可用' : '不可用'} />}>
            {neo4j.available !== false ? (
              <Row gutter={[8, 8]}>
                {Object.entries(neo4j.node_counts || neo4j).slice(0, 6).map(([k, v]: any) => (
                  <Col span={12} key={k}>
                    <Statistic title={k} value={v || 0} />
                  </Col>
                ))}
              </Row>
            ) : (
              <Empty description={neo4j.error || 'Neo4j不可用'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
      </Row>

      <div style={{ marginTop: 16, textAlign: 'right' }}>
        <Button icon={<ReloadOutlined />} onClick={fetchStats} loading={loading}>刷新统计</Button>
      </div>
    </div>
  );
}

// ===== 2. 集合管理 =====
function CollectionsTab() {
  const [collections, setCollections] = useState<CollectionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [detailVisible, setDetailVisible] = useState(false);
  const [detailData, setDetailData] = useState<any>(null);

  const fetchCollections = useCallback(async () => {
    setLoading(true);
    try {
      const res = await kcApi.listCollections() as any;
      const data = res?.data?.collections || res?.collections || [];
      setCollections(data);
    } catch (e) {
      console.error(e);
      message.error('加载集合列表失败');
      setCollections([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchCollections(); }, [fetchCollections]);

  const handleClear = async (entityType: string) => {
    try {
      const res = await kcApi.clearCollection(entityType) as any;
      if (res?.code === 0) {
        message.success(`集合 ${entityType} 已清空`);
        fetchCollections();
      } else {
        message.error(res?.message || '清空失败');
      }
    } catch (e: any) {
      message.error(e.message || '操作失败');
    }
  };

  const handleDetail = async (entityType: string) => {
    try {
      const res = await kcApi.getCollectionDetail(entityType) as any;
      setDetailData(res?.data || res);
      setDetailVisible(true);
    } catch (e: any) {
      message.error(e.message || '获取详情失败');
    }
  };

  const columns = [
    { title: '实体类型', dataIndex: 'entity_type', key: 'entity_type', render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '集合名称', dataIndex: 'collection_name', key: 'collection_name' },
    { title: '可用状态', dataIndex: 'available', key: 'available', render: (v: boolean) => <Badge status={v ? 'success' : 'error'} text={v ? '可用' : '不可用'} /> },
    { title: '记录数', dataIndex: 'row_count', key: 'row_count', render: (v: number) => <Text strong>{v}</Text> },
    {
      title: '操作', key: 'actions', width: 200,
      render: (_: any, record: CollectionInfo) => (
        <Space size="small">
          <Button size="small" icon={<EyeOutlined />} onClick={() => handleDetail(record.entity_type)}>详情</Button>
          <Popconfirm
            title="确认清空此集合？"
            description="此操作将删除集合中的所有向量数据，不可恢复。"
            onConfirm={() => handleClear(record.entity_type)}
            okText="确认清空"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>清空</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={fetchCollections} loading={loading}>刷新</Button>
      </Space>
      <Table
        dataSource={collections}
        columns={columns}
        rowKey="entity_type"
        loading={loading}
        pagination={false}
        size="small"
      />

      <Modal
        title="集合详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={800}
      >
        {detailData && (
          <div>
            <Descriptions bordered column={2} size="small">
              <Descriptions.Item label="实体类型">{detailData.entity_type}</Descriptions.Item>
              <Descriptions.Item label="集合名称">{detailData.collection_name}</Descriptions.Item>
              <Descriptions.Item label="可用">{String(detailData.available)}</Descriptions.Item>
              <Descriptions.Item label="记录数">{detailData.row_count}</Descriptions.Item>
            </Descriptions>
            {detailData.entities && detailData.entities.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <Text strong>样本数据：</Text>
                <Table
                  dataSource={detailData.entities}
                  columns={[
                    { title: 'Source ID', dataIndex: 'source_id', key: 'source_id' },
                    { title: '文本预览', dataIndex: 'text', key: 'text', ellipsis: true },
                  ]}
                  rowKey={(_r: any, i: number | undefined) => String(i)}
                  pagination={{ pageSize: 10 }}
                  size="small"
                  style={{ marginTop: 8 }}
                />
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

// ===== 3. 文档管理 =====
function DocumentsTab() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [sourceType, setSourceType] = useState('');
  const [detailVisible, setDetailVisible] = useState(false);
  const [detailData, setDetailData] = useState<any>(null);

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const res = await kcApi.listDocuments({
        keyword,
        source_type: sourceType,
        limit: 100,
      }) as any;
      const data = res?.data?.documents || res?.documents || [];
      setDocuments(data);
    } catch (e) {
      console.error(e);
      message.error('加载文档列表失败');
      setDocuments([]);
    } finally {
      setLoading(false);
    }
  }, [keyword, sourceType]);

  useEffect(() => { fetchDocuments(); }, [fetchDocuments]);

  const handleDelete = async (id: number) => {
    try {
      const res = await kcApi.deleteDocument(id) as any;
      if (res?.code === 0) {
        message.success('文档已删除');
        fetchDocuments();
      } else {
        message.error(res?.message || '删除失败');
      }
    } catch (e: any) {
      message.error(e.message || '删除失败');
    }
  };

  const handleDetail = async (id: number) => {
    try {
      const res = await kcApi.getDocumentDetail(id) as any;
      setDetailData(res?.data || res);
      setDetailVisible(true);
    } catch (e: any) {
      message.error(e.message || '获取详情失败');
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '类型', dataIndex: 'source_type', key: 'source_type', render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '文件路径', dataIndex: 'file_path', key: 'file_path', ellipsis: true },
    { title: '状态', dataIndex: 'status', key: 'status', render: (v: string) => <StatusTag status={v} /> },
    { title: '分片数', dataIndex: 'chunk_count', key: 'chunk_count' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => v ? new Date(v).toLocaleString() : '-' },
    {
      title: '操作', key: 'actions', width: 300,
      render: (_: any, record: DocumentInfo) => (
        <Space size="small">
          <Button size="small" icon={<EyeOutlined />} onClick={() => handleDetail(record.id)}>详情</Button>
          <Button size="small" icon={<BuildOutlined />} onClick={() => handleRebuild(record.id, 'embedding')}>重建Embedding</Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => handleRebuild(record.id, 'reindex')}>重新索引</Button>
          <Popconfirm
            title="确认删除此文档？"
            description="将从 MySQL/Milvus/Neo4j 三库联动删除。"
            onConfirm={() => handleDelete(record.id)}
            okText="确认删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const handleRebuild = async (id: number, action: string) => {
    const hide = message.loading('操作进行中...', 0);
    try {
      let res: any;
      if (action === 'embedding') {
        res = await kcApi.rebuildEmbedding(id);
      } else if (action === 'rechunk') {
        res = await kcApi.rechunkDocument(id);
      } else if (action === 'reindex') {
        res = await kcApi.reindexDocument(id);
      }
      hide();
      if (res?.code === 0) {
        const data = res.data || {};
        message.success(`操作完成：分片 ${data.chunk_count || 0}，向量化 ${data.embedded_count || 0}，耗时 ${data.duration || 0}s`);
      } else {
        message.error(res?.message || '操作失败');
      }
    } catch (e: any) {
      hide();
      message.error(e.message || '操作失败');
    }
  };

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="关键词搜索"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onSearch={fetchDocuments}
          style={{ width: 200 }}
          allowClear
        />
        <Select
          placeholder="来源类型"
          value={sourceType || undefined}
          onChange={(v) => setSourceType(v || '')}
          allowClear
          style={{ width: 150 }}
          options={[
            { value: '', label: '全部' },
            { value: 'pdf', label: 'PDF' },
            { value: 'word', label: 'Word' },
            { value: 'excel', label: 'Excel' },
            { value: 'markdown', label: 'Markdown' },
            { value: 'swagger', label: 'Swagger' },
            { value: 'postman', label: 'Postman' },
            { value: 'text', label: 'Text' },
          ]}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchDocuments} loading={loading}>刷新</Button>
      </Space>

      <Table
        dataSource={documents}
        columns={columns}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ pageSize: 15 }}
        scroll={{ x: 1000 }}
      />

      <Modal
        title="文档详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={900}
      >
        {detailData && (
          <div>
            <Descriptions bordered column={2} size="small">
              <Descriptions.Item label="ID">{detailData.document?.id}</Descriptions.Item>
              <Descriptions.Item label="类型">{detailData.document?.source_type}</Descriptions.Item>
              <Descriptions.Item label="文件路径" span={2}>{detailData.document?.file_path}</Descriptions.Item>
              <Descriptions.Item label="状态">{detailData.document?.status}</Descriptions.Item>
              <Descriptions.Item label="分片数">{detailData.document?.chunk_count}</Descriptions.Item>
              <Descriptions.Item label="创建时间">{detailData.document?.created_at}</Descriptions.Item>
              <Descriptions.Item label="索引时间">{detailData.document?.indexed_at || '-'}</Descriptions.Item>
            </Descriptions>

            {detailData.chunks && detailData.chunks.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <Text strong>分片列表 ({detailData.chunk_count})：</Text>
                <Table
                  dataSource={detailData.chunks}
                  columns={[
                    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
                    { title: '类型', dataIndex: 'chunk_type', key: 'chunk_type', render: (v: string) => <Tag>{v}</Tag> },
                    { title: 'Milvus ID', dataIndex: 'milvus_id', key: 'milvus_id', render: (v: number) => v > 0 ? <Tag color="green">{v}</Tag> : <Tag color="red">未索引</Tag> },
                    { title: '文本预览', dataIndex: 'text', key: 'text', ellipsis: true },
                  ]}
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                  size="small"
                  style={{ marginTop: 8 }}
                />
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

// ===== 4. Chunk 查看 =====
function ChunksTab() {
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [chunks, setChunks] = useState<ChunkInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [chunkDetail, setChunkDetail] = useState<any>(null);
  const [detailVisible, setDetailVisible] = useState(false);

  const fetchChunks = useCallback(async () => {
    if (!sourceId) return;
    setLoading(true);
    try {
      const res = await kcApi.listChunks(sourceId, { limit: 200 }) as any;
      const data = res?.data?.chunks || res?.chunks || [];
      setChunks(data);
    } catch (e) {
      console.error(e);
      message.error('加载分片列表失败');
      setChunks([]);
    } finally {
      setLoading(false);
    }
  }, [sourceId]);

  const handleChunkDetail = async (chunkId: number) => {
    try {
      const res = await kcApi.getChunkDetail(chunkId) as any;
      setChunkDetail(res?.data?.chunk || res?.chunk);
      setDetailVisible(true);
    } catch (e: any) {
      message.error(e.message || '获取详情失败');
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '来源ID', dataIndex: 'knowledge_source_id', key: 'knowledge_source_id', width: 80 },
    { title: '类型', dataIndex: 'chunk_type', key: 'chunk_type', render: (v: string) => <Tag color="purple">{v || 'content'}</Tag> },
    { title: 'Milvus ID', dataIndex: 'milvus_id', key: 'milvus_id', render: (v: number) => v > 0 ? <Tag color="green">{v}</Tag> : <Tag color="red">未索引</Tag> },
    { title: '文本预览', dataIndex: 'text', key: 'text', ellipsis: true, render: (v: string) => (v || '').substring(0, 100) + '...' },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_: any, record: ChunkInfo) => (
        <Button size="small" icon={<EyeOutlined />} onClick={() => handleChunkDetail(record.id)}>详情</Button>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <InputNumber
          placeholder="输入文档ID"
          value={sourceId || undefined}
          onChange={(v) => setSourceId(v || null)}
          min={1}
          style={{ width: 200 }}
        />
        <Button type="primary" icon={<SearchOutlined />} onClick={fetchChunks} loading={loading} disabled={!sourceId}>
          查询分片
        </Button>
      </Space>

      {chunks.length > 0 ? (
        <Table
          dataSource={chunks}
          columns={columns}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ pageSize: 20 }}
        />
      ) : (
        !loading && <Empty description={sourceId ? '该文档无分片数据' : '请输入文档ID查询'} />
      )}

      <Modal
        title="Chunk 详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={700}
      >
        {chunkDetail && (
          <Descriptions bordered column={1} size="small">
            <Descriptions.Item label="ID">{chunkDetail.id}</Descriptions.Item>
            <Descriptions.Item label="来源ID">{chunkDetail.knowledge_source_id}</Descriptions.Item>
            <Descriptions.Item label="Milvus ID">{chunkDetail.milvus_id}</Descriptions.Item>
            <Descriptions.Item label="类型">{chunkDetail.chunk_type}</Descriptions.Item>
            <Descriptions.Item label="创建时间">{chunkDetail.created_at}</Descriptions.Item>
            <Descriptions.Item label="文本内容">
              <Paragraph style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                {chunkDetail.text}
              </Paragraph>
            </Descriptions.Item>
            <Descriptions.Item label="元数据">
              <pre style={{ maxHeight: 200, overflow: 'auto', fontSize: 12 }}>
                {JSON.stringify(chunkDetail.metadata, null, 2)}
              </pre>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  );
}

// ===== 5. Embedding 状态 =====
function EmbeddingStatusTab() {
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    if (!sourceId) return;
    setLoading(true);
    try {
      const res = await kcApi.getEmbeddingStatus(sourceId) as any;
      setStatus(res?.data || res);
    } catch (e) {
      console.error(e);
      message.error('加载Embedding状态失败');
    } finally {
      setLoading(false);
    }
  }, [sourceId]);

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <InputNumber
          placeholder="输入文档ID"
          value={sourceId || undefined}
          onChange={(v) => setSourceId(v || null)}
          min={1}
          style={{ width: 200 }}
        />
        <Button type="primary" icon={<SearchOutlined />} onClick={fetchStatus} loading={loading} disabled={!sourceId}>
          查询状态
        </Button>
      </Space>

      {status && status.status === 'success' && (
        <Card title={`文档 #${sourceId} Embedding 状态`} size="small">
          <Row gutter={[16, 16]}>
            <Col span={6}>
              <Statistic title="文档状态" value={status.document_status || '-'} />
            </Col>
            <Col span={6}>
              <Statistic title="分片总数" value={status.total_chunks || 0} />
            </Col>
            <Col span={6}>
              <Statistic title="已索引" value={status.embedded_count || 0} valueStyle={{ color: '#52c41a' }} />
            </Col>
            <Col span={6}>
              <Statistic title="未索引" value={status.unembedded_count || 0} valueStyle={{ color: status.unembedded_count > 0 ? '#ff4d4f' : undefined }} />
            </Col>
          </Row>

          <div style={{ marginTop: 24 }}>
            <Text strong>向量化进度：</Text>
            <Progress
              percent={status.total_chunks > 0 ? Math.round((status.embedded_count / status.total_chunks) * 100) : 0}
              format={() => status.embedding_progress}
              status={status.unembedded_count > 0 ? 'active' : 'success'}
            />
          </div>

          {status.unembedded_chunks && status.unembedded_chunks.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <Text type="warning">未索引的分片：</Text>
              <div style={{ marginTop: 8 }}>
                {status.unembedded_chunks.map((c: any) => (
                  <Tag key={c.id} color="orange">Chunk #{c.id} ({c.chunk_type || 'content'})</Tag>
                ))}
              </div>
              <div style={{ marginTop: 12 }}>
                <Button
                  type="primary"
                  icon={<BuildOutlined />}
                  onClick={async () => {
                    if (!sourceId) return;
                    const hide = message.loading('正在重建 Embedding...', 0);
                    try {
                      const res = await kcApi.rebuildEmbedding(sourceId) as any;
                      hide();
                      if (res?.code === 0) {
                        message.success(`重建完成：${res.data?.embedded_count} 个分片已索引`);
                        fetchStatus();
                      } else {
                        message.error(res?.message || '重建失败');
                      }
                    } catch (e: any) {
                      hide();
                      message.error(e.message || '重建失败');
                    }
                  }}
                >
                  重建 Embedding
                </Button>
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

// ===== 6. Graph 查看 =====
function GraphTab() {
  const [overview, setOverview] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [nodes, setNodes] = useState<any[]>([]);
  const [selectedLabel, setSelectedLabel] = useState('');
  const [relations, setRelations] = useState<any>(null);
  const [entityId, setEntityId] = useState('');
  const [relLabel, setRelLabel] = useState('');

  const fetchOverview = useCallback(async () => {
    setLoading(true);
    try {
      const res = await kcApi.getGraphOverview() as any;
      setOverview(res?.data || res);
    } catch (e) {
      console.error(e);
      message.error('加载图谱总览失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchNodes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await kcApi.getGraphNodes({ label: selectedLabel, limit: 50 }) as any;
      const data = res?.data || res;
      if (data?.nodes) {
        setNodes(data.nodes);
      } else if (data?.node_counts) {
        setNodes(data.node_counts);
      }
    } catch (e) {
      console.error(e);
      message.error('加载节点列表失败');
    } finally {
      setLoading(false);
    }
  }, [selectedLabel]);

  const fetchRelations = useCallback(async () => {
    if (!relLabel || !entityId) return;
    setLoading(true);
    try {
      const res = await kcApi.getGraphRelations({ label: relLabel, entity_id: entityId, depth: 2 }) as any;
      setRelations(res?.data?.relations || res?.relations);
    } catch (e) {
      console.error(e);
      message.error('加载关系数据失败');
    } finally {
      setLoading(false);
    }
  }, [relLabel, entityId]);

  useEffect(() => { fetchOverview(); }, [fetchOverview]);

  const graphLabels = [
    'KnowledgeDocument', 'KnowledgeChunk', 'Entity', 'Page', 'Element',
    'API', 'DBTable', 'BusinessFlow', 'TestCase', 'Script', 'Requirement', 'Module',
  ];

  return (
    <div>
      <Spin spinning={loading}>
        <Row gutter={[16, 16]}>
          <Col span={12}>
            <Card title="图谱总览" size="small" extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchOverview}>刷新</Button>}>
              {overview?.stats ? (
                <Row gutter={[8, 8]}>
                  {Object.entries(overview.stats).map(([k, v]: any) => (
                    <Col span={8} key={k}>
                      <Statistic title={k} value={v || 0} />
                    </Col>
                  ))}
                </Row>
              ) : (
                <Empty description={overview?.message || 'Neo4j不可用'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </Card>
          </Col>

          <Col span={12}>
            <Card title="节点浏览" size="small">
              <Space style={{ marginBottom: 8 }}>
                <Select
                  placeholder="选择标签"
                  value={selectedLabel || undefined}
                  onChange={(v) => setSelectedLabel(v || '')}
                  allowClear
                  style={{ width: 200 }}
                  options={graphLabels.map(l => ({ value: l, label: l }))}
                />
                <Button size="small" icon={<SearchOutlined />} onClick={fetchNodes}>查询</Button>
              </Space>
              {nodes.length > 0 && (
                <Table
                  dataSource={nodes}
                  columns={[
                    { title: '标签', dataIndex: 'label', key: 'label', render: (v: string) => <Tag color="blue">{v}</Tag> },
                    { title: '数量', dataIndex: 'count', key: 'count' },
                    ...(nodes[0]?.properties ? [{
                      title: '属性', dataIndex: 'properties', key: 'properties',
                      render: (v: any) => <Tooltip title={JSON.stringify(v, null, 2)}><Text ellipsis style={{ maxWidth: 200 }}>{JSON.stringify(v)}</Text></Tooltip>,
                    }] : []),
                  ]}
                  rowKey={(_r: any, i: number | undefined) => String(i)}
                  pagination={{ pageSize: 10 }}
                  size="small"
                />
              )}
            </Card>
          </Col>
        </Row>

        <Card title="关系图查看" size="small" style={{ marginTop: 16 }}>
          <Space style={{ marginBottom: 8 }}>
            <Select
              placeholder="标签"
              value={relLabel || undefined}
              onChange={(v) => setRelLabel(v || '')}
              allowClear
              style={{ width: 200 }}
              options={graphLabels.map(l => ({ value: l, label: l }))}
            />
            <Input
              placeholder="实体ID"
              value={entityId}
              onChange={(e) => setEntityId(e.target.value)}
              style={{ width: 200 }}
            />
            <Button type="primary" icon={<SearchOutlined />} onClick={fetchRelations} disabled={!relLabel || !entityId}>
              查询关系
            </Button>
          </Space>
          {relations && (
            <div>
              {relations.nodes && relations.nodes.length > 0 ? (
                <div>
                  <Text strong>节点 ({relations.nodes.length})：</Text>
                  <div style={{ marginTop: 4 }}>
                    {relations.nodes.map((n: any, i: number) => (
                      <Tag key={i} color="blue">{n.labels?.[0] || 'Node'}: {JSON.stringify(n.properties).substring(0, 50)}</Tag>
                    ))}
                  </div>
                </div>
              ) : (
                <Empty description="无关系数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
              {relations.edges && relations.edges.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <Text strong>关系 ({relations.edges.length})：</Text>
                  <div style={{ marginTop: 4 }}>
                    {relations.edges.map((e: any, i: number) => (
                      <Tag key={i} color="purple">{e.type}: {JSON.stringify(e.properties || {}).substring(0, 50)}</Tag>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>
      </Spin>
    </div>
  );
}

// ===== 7. 搜索测试 =====
function SearchTestTab() {
  const [searchType, setSearchType] = useState<'fulltext' | 'semantic' | 'hybrid'>('fulltext');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [duration, setDuration] = useState(0);
  const [form] = Form.useForm();

  const handleSearch = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      setResults([]);
      setDuration(0);

      let res: any;
      if (searchType === 'fulltext') {
        res = await kcApi.fulltextSearch({
          keyword: values.keyword,
          source_type: values.source_type || '',
          limit: values.limit || 20,
        });
      } else if (searchType === 'semantic') {
        res = await kcApi.semanticSearch({
          query: values.query,
          entity_types: values.entity_types || 'chunk',
          top_k: values.top_k || 10,
        });
      } else {
        res = await kcApi.hybridSearch({
          keyword: values.keyword,
          query: values.query,
          entity_types: ['chunk'],
          top_k: values.top_k || 10,
        });
      }

      const data = res?.data || res;
      if (data?.status === 'success' || data?.results) {
        setResults(data.results || []);
        setDuration(data.duration || 0);
      } else {
        message.error(data?.message || '搜索失败');
      }
    } catch (e: any) {
      if (e.errorFields) return; // form validation error
      message.error(e.message || '搜索失败');
    } finally {
      setLoading(false);
    }
  };

  const columns = [
    {
      title: '排名', key: 'rank', width: 60,
      render: (_: any, __: any, i: number) => i + 1,
    },
    {
      title: '类型', key: 'search_type',
      render: (_: any, r: SearchResult) => (
        <Space direction="vertical" size={0}>
          {r.search_type && <Tag color={r.search_type === 'semantic' ? 'blue' : 'green'}>{r.search_type}</Tag>}
          {r.chunk_type && <Tag>{r.chunk_type}</Tag>}
          {r.source_type && <Tag color="purple">{r.source_type}</Tag>}
        </Space>
      ),
    },
    {
      title: '分数', key: 'score', width: 120,
      render: (_: any, r: SearchResult) => (
        <Text strong style={{ color: '#1890ff' }}>
          {r.hybrid_score ? r.hybrid_score : r.score}
        </Text>
      ),
      sorter: (a: SearchResult, b: SearchResult) => (a.hybrid_score || a.score) - (b.hybrid_score || b.score),
      defaultSortOrder: 'descend' as const,
    },
    {
      title: '来源', key: 'source', width: 120,
      render: (_: any, r: SearchResult) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {r.source_id ? `#${r.source_id}` : r.chunk_id ? `Chunk #${r.chunk_id}` : '-'}
        </Text>
      ),
    },
    {
      title: '文本内容', key: 'text',
      render: (_: any, r: SearchResult) => (
        <Tooltip title={r.text}>
          <Text ellipsis style={{ maxWidth: 500, display: 'block' }}>{r.text}</Text>
        </Tooltip>
      ),
    },
  ];

  return (
    <div>
      <Card size="small">
        <Tabs
          activeKey={searchType}
          onChange={(k) => setSearchType(k as any)}
          size="small"
          items={[
            { key: 'fulltext', label: <span><FileSearchOutlined /> 全文检索</span> },
            { key: 'semantic', label: <span><SearchOutlined /> 语义检索</span> },
            { key: 'hybrid', label: <span><ThunderboltOutlined /> 混合检索</span> },
          ]}
        />

        <Form form={form} layout="inline" style={{ marginBottom: 16 }}>
          {searchType === 'fulltext' && (
            <>
              <Form.Item name="keyword" rules={[{ required: true, message: '请输入关键词' }]}>
                <Input placeholder="搜索关键词" style={{ width: 250 }} />
              </Form.Item>
              <Form.Item name="source_type">
                <Select
                  placeholder="来源类型"
                  allowClear
                  style={{ width: 150 }}
                  options={[
                    { value: '', label: '全部' },
                    { value: 'pdf', label: 'PDF' },
                    { value: 'word', label: 'Word' },
                    { value: 'markdown', label: 'Markdown' },
                    { value: 'swagger', label: 'Swagger' },
                    { value: 'text', label: 'Text' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="limit" initialValue={20}>
                <InputNumber placeholder="数量" min={1} max={100} style={{ width: 100 }} />
              </Form.Item>
            </>
          )}

          {searchType === 'semantic' && (
            <>
              <Form.Item name="query" rules={[{ required: true, message: '请输入查询语句' }]}>
                <Input placeholder="语义查询语句" style={{ width: 300 }} />
              </Form.Item>
              <Form.Item name="entity_types" initialValue="chunk">
                <Select
                  style={{ width: 150 }}
                  options={[
                    { value: 'chunk', label: 'Chunk' },
                    { value: 'requirement', label: 'Requirement' },
                    { value: 'page', label: 'Page' },
                    { value: 'case', label: 'Case' },
                    { value: 'script', label: 'Script' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="top_k" initialValue={10}>
                <InputNumber placeholder="Top K" min={1} max={50} style={{ width: 100 }} />
              </Form.Item>
            </>
          )}

          {searchType === 'hybrid' && (
            <>
              <Form.Item name="keyword" rules={[{ required: true, message: '请输入关键词' }]}>
                <Input placeholder="全文检索关键词" style={{ width: 200 }} />
              </Form.Item>
              <Form.Item name="query">
                <Input placeholder="语义查询语句（可选）" style={{ width: 200 }} />
              </Form.Item>
              <Form.Item name="top_k" initialValue={10}>
                <InputNumber placeholder="Top K" min={1} max={50} style={{ width: 100 }} />
              </Form.Item>
            </>
          )}

          <Form.Item>
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>
              搜索
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <div style={{ marginTop: 16 }}>
        {results.length > 0 ? (
          <>
            <Space style={{ marginBottom: 8 }}>
              <Tag color="blue">{searchType === 'fulltext' ? '全文检索' : searchType === 'semantic' ? '语义检索' : '混合检索'}</Tag>
              <Text type="secondary">共 {results.length} 条结果，耗时 {duration}s</Text>
            </Space>
            <Table
              dataSource={results}
              columns={columns}
              rowKey={(_r: any, i: number | undefined) => String(i)}
              loading={loading}
              size="small"
              pagination={{ pageSize: 10 }}
            />
          </>
        ) : (
          !loading && <Empty description="输入搜索条件后点击搜索" />
        )}
      </div>
    </div>
  );
}

// ===== 8. 知识导入 =====
function KnowledgeImportTab() {
  const [uploading, setUploading] = useState(false);
  const [lastResult, setLastResult] = useState<any>(null);
  const [importHistory, setImportHistory] = useState<any[]>([]);
  const [form] = Form.useForm();

  const handleUpload = async (file: File) => {
    setUploading(true);
    setLastResult(null);
    try {
      const values = await form.validateFields();
      const res = await kcApi.uploadKnowledge(file, {
        project_id: values.project_id || 'default',
        source_type: values.source_type || '',
        title: values.title || '',
      }) as any;
      const data = res?.data || res;
      setLastResult(data);
      if (data?.status === 'success' || data?.status === 'partial') {
        message.success(`导入完成：${data.chunk_count || 0} 个分片，向量化 ${data.milvus_inserted || 0} 条`);
        setImportHistory(prev => [{ ...data, file_name: file.name, time: new Date().toLocaleString() }, ...prev].slice(0, 10));
      } else {
        message.error(data?.errors?.[0] || '导入失败');
      }
    } catch (e: any) {
      if (e.errorFields) return;
      message.error(e.message || '导入失败');
    } finally {
      setUploading(false);
    }
    return false; // prevent antd Upload auto upload
  };

  return (
    <div>
      <Alert
        message="知识导入"
        description="上传文档后系统自动解析、分块、向量化并入库。支持 PDF、Word、Markdown、Swagger 等格式。"
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Form form={form} layout="vertical" style={{ maxWidth: 600 }}>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="source_type" label="文档类型" initialValue="pdf">
              <Select options={[
                { value: 'pdf', label: 'PDF' },
                { value: 'word', label: 'Word' },
                { value: 'markdown', label: 'Markdown' },
                { value: 'swagger', label: 'Swagger/OpenAPI' },
                { value: 'text', label: '文本' },
              ]} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="project_id" label="项目ID" initialValue="default">
              <Input placeholder="项目标识" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="title" label="标题（可选）">
              <Input placeholder="文档标题" />
            </Form.Item>
          </Col>
        </Row>
      </Form>

      <Upload.Dragger
        accept=".pdf,.doc,.docx,.md,.markdown,.json,.txt"
        multiple={false}
        showUploadList={false}
        beforeUpload={handleUpload}
        disabled={uploading}
      >
        <p className="ant-upload-drag-icon">
          {uploading ? <Spin size="large" /> : <CloudUploadOutlined style={{ fontSize: 48, color: '#1890ff' }} />}
        </p>
        <p className="ant-upload-text">
          {uploading ? '正在导入...' : '点击或拖拽文件到此区域上传'}
        </p>
        <p className="ant-upload-hint">
          支持 PDF、Word、Markdown、Swagger、文本格式
        </p>
      </Upload.Dragger>

      {lastResult && (
        <Card title="导入结果" size="small" style={{ marginTop: 16 }}>
          <Row gutter={[16, 16]}>
            <Col span={6}>
              <Statistic title="状态" value={lastResult.status || '-'} valueStyle={{ color: lastResult.status === 'success' ? '#52c41a' : '#faad14' }} />
            </Col>
            <Col span={6}>
              <Statistic title="分片数量" value={lastResult.chunk_count || 0} />
            </Col>
            <Col span={6}>
              <Statistic title="向量化" value={lastResult.milvus_inserted || 0} suffix="条" />
            </Col>
            <Col span={6}>
              <Statistic title="耗时" value={lastResult.duration || 0} suffix="s" />
            </Col>
          </Row>
          {lastResult.errors && lastResult.errors.length > 0 && (
            <Alert
              style={{ marginTop: 12 }}
              message="部分错误"
              description={lastResult.errors.join('; ')}
              type="warning"
              showIcon
            />
          )}
        </Card>
      )}

      {importHistory.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Divider>本次导入历史</Divider>
          <Table
            dataSource={importHistory}
            columns={[
              { title: '文件名', dataIndex: 'file_name', key: 'file_name' },
              { title: '状态', dataIndex: 'status', key: 'status', render: (v: string) => <Tag color={v === 'success' ? 'green' : 'orange'}>{v}</Tag> },
              { title: '分片数', dataIndex: 'chunk_count', key: 'chunk_count' },
              { title: '向量化', dataIndex: 'milvus_inserted', key: 'milvus_inserted' },
              { title: '时间', dataIndex: 'time', key: 'time' },
            ]}
            rowKey={(_r: any, i: number | undefined) => String(i)}
            pagination={false}
            size="small"
          />
        </div>
      )}
    </div>
  );
}

// ===== 9. AI检索配置 =====
function AIConfigTab() {
  const [health, setHealth] = useState<any>(null);
  const [types, setTypes] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [testQuery, setTestQuery] = useState('');
  const [testType, setTestType] = useState('test_case');
  const [testResult, setTestResult] = useState<any>(null);
  const [testing, setTesting] = useState(false);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    try {
      const [healthRes, typesRes] = await Promise.all([
        kcApi.getContextRouterHealth() as any,
        kcApi.getContextTypes() as any,
      ]);
      setHealth(healthRes?.data || healthRes);
      setTypes(typesRes?.data?.types || typesRes?.types || []);
    } catch (e) {
      console.error(e);
      message.error('加载配置状态失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchHealth(); }, [fetchHealth]);

  const handleTest = async () => {
    if (!testQuery.trim()) {
      message.warning('请输入查询内容');
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const res = await kcApi.retrieveContext({
        query: testQuery,
        context_type: testType,
        top_k: 5,
      }) as any;
      setTestResult(res?.data || res);
    } catch (e: any) {
      message.error(e.message || '查询失败');
    } finally {
      setTesting(false);
    }
  };

  const dataSourceStatus = (name: string, info: any) => (
    <Card title={name} size="small" extra={
      <Badge status={info?.status === 'healthy' ? 'success' : 'error'} text={info?.status === 'healthy' ? '可用' : '不可用'} />
    }>
      {info?.status === 'healthy' ? (
        <div>
          {info?.collections && (
            <div style={{ marginBottom: 8 }}>
              {info.collections.map((c: string) => (
                <Tag key={c} color="blue">{c}</Tag>
              ))}
            </div>
          )}
          {info?.base_url && <Text type="secondary" style={{ fontSize: 12 }}>{info.base_url}</Text>}
          {info?.request_count !== undefined && (
            <Statistic title="查询次数" value={info.request_count} style={{ marginTop: 8 }} />
          )}
        </div>
      ) : (
        <Empty description={info?.error || '服务不可用'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}
    </Card>
  );

  return (
    <div>
      <Spin spinning={loading}>
        <Row gutter={[16, 16]}>
          <Col span={6}>
            {dataSourceStatus('业务数据存储', health?.mysql)}
          </Col>
          <Col span={6}>
            {dataSourceStatus('向量检索引擎', health?.milvus)}
          </Col>
          <Col span={6}>
            {dataSourceStatus('关系图谱引擎', health?.neo4j)}
          </Col>
          <Col span={6}>
            {dataSourceStatus('知识构建引擎', health?.r2r)}
          </Col>
        </Row>

        {types.length > 0 && (
          <Card title="支持的检索类型" size="small" style={{ marginTop: 16 }}>
            <Table
              dataSource={types}
              columns={[
                { title: '类型', dataIndex: 'name', key: 'name', render: (v: string) => <Tag color="blue">{v}</Tag> },
                { title: '数据源', dataIndex: 'sources', key: 'sources', render: (v: string[]) => v?.map(s => <Tag key={s}>{s}</Tag>) },
                { title: '说明', dataIndex: 'description', key: 'description' },
              ]}
              rowKey="name"
              pagination={false}
              size="small"
            />
          </Card>
        )}

        <Card title="检索测试" size="small" style={{ marginTop: 16 }}>
          <Space style={{ marginBottom: 16, width: '100%' }}>
            <Select
              value={testType}
              onChange={setTestType}
              style={{ width: 200 }}
              options={types.map(t => ({ value: t.name, label: t.name }))}
            />
            <Input
              placeholder="输入查询内容"
              value={testQuery}
              onChange={(e) => setTestQuery(e.target.value)}
              style={{ width: 400 }}
              onPressEnter={handleTest}
            />
            <Button type="primary" icon={<SearchOutlined />} onClick={handleTest} loading={testing}>
              检索
            </Button>
          </Space>

          {testResult && (
            <div>
              <Space style={{ marginBottom: 8 }}>
                <Tag color="blue">{testResult.context_type}</Tag>
                <Text type="secondary">共 {testResult.total || 0} 条结果，耗时 {testResult.latency_ms || 0}ms</Text>
              </Space>
              <Table
                dataSource={testResult.results || []}
                columns={[
                  { title: '来源', dataIndex: 'source', key: 'source', render: (v: string) => <Tag>{v}</Tag> },
                  { title: '分数', dataIndex: 'score', key: 'score', render: (v: number) => <Text strong style={{ color: '#1890ff' }}>{v?.toFixed(4)}</Text> },
                  { title: '内容', dataIndex: 'text', key: 'text', ellipsis: true },
                ]}
                rowKey={(_r: any, i: number | undefined) => String(i)}
                pagination={{ pageSize: 5 }}
                size="small"
              />
            </div>
          )}
        </Card>
      </Spin>

      <div style={{ marginTop: 16, textAlign: 'right' }}>
        <Button icon={<ReloadOutlined />} onClick={fetchHealth} loading={loading}>刷新状态</Button>
      </div>
    </div>
  );
}
