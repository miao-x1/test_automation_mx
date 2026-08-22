import { useNavigate } from 'react-router-dom';
import { Card, Button, Typography, Space } from 'antd';
import { RocketOutlined, PlusOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

/**
 * AI 用例生成入口
 *
 * 原 CaseGenerate 组件已合并到统一的任务创建流程，
 * 此页面引导用户前往 /task/create 进行 AI 驱动的用例生成。
 */
export default function GeneratePage() {
  const navigate = useNavigate();

  return (
    <Card style={{ textAlign: 'center', padding: '40px 20px' }}>
      <RocketOutlined style={{ fontSize: 48, color: '#1890ff', marginBottom: 16 }} />
      <Title level={4}>AI 智能用例生成</Title>
      <Paragraph type="secondary" style={{ maxWidth: 400, margin: '0 auto 24px' }}>
        输入测试需求描述，AI 自动完成用例生成、脚本编写和自动执行
      </Paragraph>
      <Space>
        <Button
          type="primary"
          size="large"
          icon={<PlusOutlined />}
          onClick={() => navigate('/task/create')}
        >
          开始生成
        </Button>
      </Space>
    </Card>
  );
}
