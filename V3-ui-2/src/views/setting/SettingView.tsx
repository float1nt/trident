import { useEffect, useState } from "react";
import { Alert, Button, Checkbox, Descriptions, Form, InputNumber, Spin, Tag } from "antd";
import { useApi } from "@/hooks/useApi";
import IpRangeFormList, { EMPTY_IP_RANGE } from "@/components/IpRangeFormList";
import { SectionTitle } from "@/components/SectionTitle";
import {
  applyCollectionSettings,
  getCollectionAgentStatus,
  getCollectionProtocols,
  getCollectionSettings,
  refreshCollectionAgentStatus,
  saveCollectionSettings,
  type CollectionApplyResult,
  type CollectionAgentStatusResponse,
  type CollectionSettings,
  type ProtocolOption,
} from "@/api/services/SettingService";
import "./SettingView.css";

type SettingFormValues = CollectionSettings;

export default function SettingView() {
  const [form] = Form.useForm<SettingFormValues>();
  const { loading, run: runLoad } = useApi({ initialLoading: true });
  const { loading: submitting, run: runSave } = useApi();
  const { loading: refreshingAgentStatus, run: runRefreshAgentStatus } = useApi({
    successMessage: "采集机状态已刷新",
  });
  const [protocolOptions, setProtocolOptions] = useState<ProtocolOption[]>([]);
  const [revision, setRevision] = useState<number>();
  const [applyResult, setApplyResult] = useState<CollectionApplyResult | null>(null);
  const [agentStatus, setAgentStatus] = useState<CollectionAgentStatusResponse | null>(null);
  const [agentStatusAvailable, setAgentStatusAvailable] = useState(true);

  const updateState = (state: Awaited<ReturnType<typeof getCollectionSettings>>) => {
    setRevision(state.revision);
    setApplyResult(state.lastApply ?? null);
    form.setFieldsValue({
      ...state.settings,
      sourceIpRanges:
        state.settings.sourceIpRanges?.length > 0
          ? state.settings.sourceIpRanges
          : [{ ...EMPTY_IP_RANGE }],
      destIpRanges:
        state.settings.destIpRanges?.length > 0
          ? state.settings.destIpRanges
          : [{ ...EMPTY_IP_RANGE }],
    });
  };

  useEffect(() => {
    let cancelled = false;

    void runLoad(async () => {
      const [state, protocols] = await Promise.all([
        getCollectionSettings(),
        getCollectionProtocols(),
      ]);
      if (cancelled) return;
      setProtocolOptions(protocols);
      updateState(state);
    });

    return () => {
      cancelled = true;
    };
  }, [form, runLoad]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;

    const refresh = async (): Promise<boolean> => {
      try {
        const status = await refreshCollectionAgentStatus();
        if (!cancelled) {
          setAgentStatus(status);
          setAgentStatusAvailable(true);
        }
        return true;
      } catch {
        if (!cancelled) {
          setAgentStatusAvailable(false);
        }
        return false;
      }
    };

    const readCached = async () => {
      try {
        const status = await getCollectionAgentStatus();
        if (!cancelled) {
          setAgentStatus(status);
        }
      } catch {
        if (!cancelled) {
          setAgentStatusAvailable(false);
          if (timer) clearInterval(timer);
        }
      }
    };

    void refresh().then((available) => {
      if (!cancelled && available) {
        timer = setInterval(() => void readCached(), 15_000);
      }
    });

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  const handleSubmit = async (values: SettingFormValues) => {
    const result = await runSave(() => saveCollectionSettings(values));
    if (result) {
      setRevision(result.revision);
      setApplyResult(result.apply);
      return;
    }
    await refreshSettingsState();
  };

  const handleRetryApply = async () => {
    const result = await runSave(() => applyCollectionSettings());
    if (result) {
      setApplyResult(result);
      return;
    }
    await refreshSettingsState();
  };

  const refreshSettingsState = async () => {
    try {
      updateState(await getCollectionSettings());
    } catch {
      // The request interceptor already reports refresh failures.
    }
  };

  const handleRefreshAgentStatus = async () => {
    const status = await runRefreshAgentStatus(() => refreshCollectionAgentStatus());
    if (status) {
      setAgentStatus(status);
      setAgentStatusAvailable(true);
      return;
    }
    setAgentStatusAvailable(false);
  };

  return (
    <div className="setting-page bg-[#f6faff] p-[12px] h-[calc(100vh-86px)] overflow-y-auto w-full rounded-[8px]">
      <div className="setting-card bg-white rounded-[8px] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
        <div className="mb-6 flex items-center justify-between">
          <SectionTitle>采集配置</SectionTitle>
          {applyResult && !applyResult.applied && (
            <Button size="small" onClick={handleRetryApply} loading={submitting}>
              重新下发
            </Button>
          )}
        </div>

        {applyResult && (
          <Alert
            className="mb-4"
            type={applyResult.applied ? "success" : "warning"}
            showIcon
            message={applyResult.applied ? "配置已保存并下发" : "配置已保存，但部分采集机未生效"}
            description={
              <div>
                <div>当前配置版本：{revision ?? "-"}</div>
                {applyResult.message && <div>{applyResult.message}</div>}
                {applyResult.agents.map((agent) => (
                  <div key={`${agent.name}-${agent.url}`}>
                    {agent.name} ({agent.url})：{agent.ok ? "成功" : agent.error || "失败"}
                  </div>
                ))}
              </div>
            }
          />
        )}

        <Spin spinning={refreshingAgentStatus}>
          {!agentStatusAvailable && (
            <Alert
              className="mb-4"
              type="warning"
              showIcon
              message="暂时无法读取采集机状态"
              description="配置编辑与下发仍可继续。完成分析侧阶段二部署后，可手动重试状态刷新。"
              action={
                <Button
                  size="small"
                  loading={refreshingAgentStatus}
                  onClick={() => void handleRefreshAgentStatus()}
                >
                  重试状态刷新
                </Button>
              }
            />
          )}

          {agentStatusAvailable && agentStatus && (
            <div className="mb-4 rounded-[6px] border border-[#e5eaf3] ">
              <div className="mb-3 flex items-center justify-between">
                <SectionTitle>采集机状态</SectionTitle>
                <Button
                  size="small"
                  loading={refreshingAgentStatus}
                  onClick={() => void handleRefreshAgentStatus()}
                >
                  刷新状态
                </Button>
              </div>
              {agentStatus.agents.length === 0 ? (
                <Alert type="info" showIcon message="尚未配置采集机 agent" />
              ) : (
                agentStatus.agents.map((agent) => (
                  <Descriptions
                    key={`${agent.name}-${agent.url}`}
                    className="mb-3"
                    bordered
                    size="small"
                    column={3}
                    title={
                      <span className="inline-flex items-center gap-2">
                        {agent.name}
                        <Tag color={agent.reachable ? "green" : "red"}>
                          {agent.reachable ? "在线" : "离线"}
                        </Tag>
                        <Tag color={agent.effective ? "green" : "orange"}>
                          {agent.effective ? "已生效" : "未生效"}
                        </Tag>
                      </span>
                    }
                  >
                    <Descriptions.Item label="地址">{agent.url}</Descriptions.Item>
                    <Descriptions.Item label="网卡">{agent.status?.iface ?? "-"}</Descriptions.Item>
                    <Descriptions.Item label="Suricata">
                      {agent.status?.suricata?.running ? "运行中" : agent.status?.suricata?.status ?? "-"}
                    </Descriptions.Item>
                    <Descriptions.Item label="期望版本">{agent.desiredRevision ?? "-"}</Descriptions.Item>
                    <Descriptions.Item label="生效版本">{agent.effectiveRevision ?? "-"}</Descriptions.Item>
                    <Descriptions.Item label="Redis 队列">
                      {agent.status?.redis
                        ? `${agent.status.redis.type ?? "-"} / ${agent.status.redis.length ?? "-"}`
                        : "-"}
                    </Descriptions.Item>
                    <Descriptions.Item label="采样时间" span={agent.error ? 1 : 3}>
                      {agent.sampledAt ?? agent.status?.sampledAt ?? "-"}
                    </Descriptions.Item>
                    {agent.error && (
                      <Descriptions.Item label="错误" span={2}>
                        {agent.error}
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                ))
              )}
            </div>
          )}
        </Spin>

        <Spin spinning={loading}>
          <Form<SettingFormValues>
            form={form}
            layout="horizontal"
            labelCol={{ flex: "140px" }}
            wrapperCol={{ flex: "1" }}
            colon={false}
            requiredMark
            onFinish={handleSubmit}
            className="setting-form max-w-[900px]"
          >
            <Form.Item
              label="最大流量限制"
              name="maxTrafficLimitGbps"
              rules={[
                { required: true, message: "请输入最大流量限制" },
                {
                  type: "number",
                  min: 0.01,
                  message: "流量限制须大于 0",
                },
              ]}
            >
              <InputNumber
                min={0.01}
                step={0.1}
                precision={2}
                placeholder="请输入数字"
                className="w-[200px]"
                addonAfter="Gbps"
              />
            </Form.Item>

            <Form.Item label="采集源 IP 范围" required>
              <IpRangeFormList name="sourceIpRanges" />
            </Form.Item>

            <Form.Item label="采集目的 IP 范围" required>
              <IpRangeFormList name="destIpRanges" />
            </Form.Item>

            <Form.Item
              label="采集协议"
              name="protocols"
              rules={[
                {
                  type: "array",
                  min: 1,
                  message: "请至少选择一种协议",
                },
              ]}
            >
              <Checkbox.Group
                options={protocolOptions.map((item) => ({
                  label: item.label,
                  value: item.value,
                }))}
                className="setting-protocol-group"
              />
            </Form.Item>

            {/* <Form.Item wrapperCol={{ offset: 140 }}>
              <Button type="primary" htmlType="submit" loading={submitting}>
                确认
              </Button>
            </Form.Item> */}
            <Button className="mb-[20px]" type="primary" htmlType="submit" loading={submitting}>
                确认
              </Button>
          </Form>
        </Spin>
      </div>
    </div>
  );
}
