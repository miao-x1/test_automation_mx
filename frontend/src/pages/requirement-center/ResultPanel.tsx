import React, { useState } from 'react';
import {
  Card,
  Tabs,
  Tag,
  Typography,
  Space,
  Statistic,
  Row,
  Col,
  Table,
  Alert,
  Button,
  Input,
  List,
} from 'antd';
import {
  CheckCircleOutlined,
  EditOutlined,
  ExperimentOutlined,
  WarningOutlined,
  AimOutlined,
  BranchesOutlined,
  BulbOutlined,
} from '@ant-design/icons';
import type { RequirementSummaryData } from '../../services/requirementCenter';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

interface ResultPanelProps {
  summary: RequirementSummaryData | null;
  finalized: boolean;
  onFinalize: (requirement: string) => void;
  finalizing: boolean;
}

const ResultPanel: React.FC<ResultPanelProps> = ({ summary, finalized, onFinalize, finalizing }) => {
  const [editing, setEditing] = useState(false);
  const [editedText, setEditedText] = useState('');

  if (!summary) {
    return (
      <Card title="AI最终理解结果" style={{ marginTop: 16 }}>
        <Alert type="info" message="等待AI分析完成后，结果将在此展示" showIcon />
      </Card>
    );
  }

  const handleEdit = () => {
    setEditedText(summary.requirement_text || '');
    setEditing(true);
  };

  const handleConfirm = () => {
    onFinalize(editing ? editedText : summary.requirement_text || '');
  };

  const tabItems = [
    {
      key: 'overview',
      label: (
        <span>
          <BulbOutlined /> 需求摘要
        </span>
      ),
      children: (
        <>
          {editing ? (
            <>
              <TextArea
                rows={10}
                value={editedText}
                onChange={(e) => setEditedText(e.target.value)}
              />
              <Space style={{ marginTop: 8 }}>
                <Button onClick={() => setEditing(false)}>取消</Button>
                <Button type="primary" onClick={handleConfirm} loading={finalizing}>
                  确认创建任务
                </Button>
              </Space>
            </>
          ) : (
            <>
              <Paragraph>{summary.requirement_text}</Paragraph>
              {!finalized && (
                <Space style={{ marginTop: 16 }}>
                  <Button icon={<EditOutlined />} onClick={handleEdit}>
                    修改需求
                  </Button>
                  <Button
                    type="primary"
                    icon={<CheckCircleOutlined />}
                    onClick={handleConfirm}
                    loading={finalizing}
                  >
                    确认创建任务
                  </Button>
                </Space>
              )}
              {finalized && (
                <Alert
                  type="success"
                  message="需求已确认，任务已创建"
                  showIcon
                  style={{ marginTop: 16 }}
                />
              )}
            </>
          )}
        </>
      ),
    },
    {
      key: 'elements',
      label: (
        <span>
          <ExperimentOutlined /> 页面元素 ({summary.page_elements?.length || 0})
        </span>
      ),
      children: (
        <Table
          size="small"
          dataSource={summary.page_elements?.map((el: any, i: number) => ({ ...el, key: i })) || []}
          columns={[
            { title: '名称', dataIndex: 'name', key: 'name' },
            { title: '类型', dataIndex: 'type', key: 'type' },
            { title: '定位器', dataIndex: 'locator', key: 'locator', ellipsis: true },
            { title: '来源', dataIndex: 'source', key: 'source' },
          ]}
          pagination={{ pageSize: 10 }}
        />
      ),
    },
    {
      key: 'flows',
      label: (
        <span>
          <BranchesOutlined /> 业务流程 ({summary.business_flows?.length || 0})
        </span>
      ),
      children: (
        <List
          size="small"
          dataSource={summary.business_flows || []}
          renderItem={(flow: any, i) => (
            <List.Item>
              <Space>
                <Tag color="blue">{i + 1}</Tag>
                <Text>{typeof flow === 'string' ? flow : flow.goal || flow.step || JSON.stringify(flow)}</Text>
              </Space>
            </List.Item>
          )}
        />
      ),
    },
    {
      key: 'goals',
      label: (
        <span>
          <AimOutlined /> 测试目标 ({summary.test_goals?.length || 0})
        </span>
      ),
      children: (
        <List
          size="small"
          dataSource={summary.test_goals || []}
          renderItem={(goal: any, i) => (
            <List.Item>
              <Space>
                <Tag color="green">{i + 1}</Tag>
                <Text>{typeof goal === 'string' ? goal : goal.goal || JSON.stringify(goal)}</Text>
                {goal.type && <Tag>{goal.type}</Tag>}
              </Space>
            </List.Item>
          )}
        />
      ),
    },
    {
      key: 'risks',
      label: (
        <span>
          <WarningOutlined /> 风险点 ({summary.risk_points?.length || 0})
        </span>
      ),
      children: (
        <List
          size="small"
          dataSource={summary.risk_points || []}
          renderItem={(risk: any) => (
            <List.Item>
              <Space>
                <Tag color={risk.level === 'high' ? 'red' : risk.level === 'medium' ? 'orange' : 'green'}>
                  {risk.level}
                </Tag>
                <Text>{risk.risk}</Text>
                {risk.category && <Tag>{risk.category}</Tag>}
              </Space>
            </List.Item>
          )}
        />
      ),
    },
  ];

  return (
    <Card
      title="AI最终理解结果"
      style={{ marginTop: 16 }}
      extra={
        <Space>
          <Statistic
            title="置信度"
            value={Math.round((summary.confidence || 0) * 100)}
            suffix="%"
            valueStyle={{
              fontSize: 14,
              color: summary.confidence > 0.6 ? '#3f8600' : '#cf1322',
            }}
          />
        </Space>
      }
    >
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Statistic title="建议测试类型" value={summary.recommended_test_types?.join(', ') || '-'} />
        </Col>
        <Col span={6}>
          <Statistic title="关联页面" value={summary.related_pages?.length || 0} />
        </Col>
        <Col span={6}>
          <Statistic title="来源Agent" value={summary.source_agents?.length || 0} />
        </Col>
        <Col span={6}>
          <Statistic title="分析数量" value={summary.analysis_count || 0} />
        </Col>
      </Row>

      <Tabs items={tabItems} type="card" />
    </Card>
  );
};

export default ResultPanel;
