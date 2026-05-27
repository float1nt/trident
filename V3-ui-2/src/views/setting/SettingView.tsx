import { useEffect, useState } from "react";
import { Button, Checkbox, Form, InputNumber, Spin } from "antd";
import { useApi } from "@/hooks/useApi";
import IpRangeFormList, { EMPTY_IP_RANGE } from "@/components/IpRangeFormList";
import {
  getCollectionProtocols,
  getCollectionSettings,
  saveCollectionSettings,
  type CollectionSettings,
  type ProtocolOption,
} from "@/api/services/SettingService";
import "./SettingView.css";

type SettingFormValues = CollectionSettings;

export default function SettingView() {
  const [form] = Form.useForm<SettingFormValues>();
  const { loading, run: runLoad } = useApi({ initialLoading: true });
  const { loading: submitting, run: runSave } = useApi();
  const [protocolOptions, setProtocolOptions] = useState<ProtocolOption[]>([]);

  useEffect(() => {
    let cancelled = false;

    void runLoad(async () => {
      const [settings, protocols] = await Promise.all([
        getCollectionSettings(),
        getCollectionProtocols(),
      ]);
      if (cancelled) return;
      setProtocolOptions(protocols);
      form.setFieldsValue({
        ...settings,
        sourceIpRanges:
          settings.sourceIpRanges?.length > 0
            ? settings.sourceIpRanges
            : [{ ...EMPTY_IP_RANGE }],
        destIpRanges:
          settings.destIpRanges?.length > 0
            ? settings.destIpRanges
            : [{ ...EMPTY_IP_RANGE }],
      });
    });

    return () => {
      cancelled = true;
    };
  }, [form, runLoad]);

  const handleSubmit = async (values: SettingFormValues) => {
    await runSave(() => saveCollectionSettings(values));
  };

  return (
    <div className="setting-page bg-[#f6faff] p-[12px] h-[calc(100vh-86px)] overflow-y-auto w-full rounded-[8px]">
      <div className="setting-card bg-white rounded-[8px] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
        <div className="mb-6 flex h-6 items-center gap-2 text-[16px] font-medium text-[#333]">
          <span
            className="h-[16px] w-[3px] shrink-0 rounded-[2px] bg-[#4368f0]"
            aria-hidden
          />
          采集配置
        </div>

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
