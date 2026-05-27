import { useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Form, Input, Button } from "antd";
import { useApi } from "@/hooks/useApi";
import { UserOutlined, LockOutlined } from "@ant-design/icons";
import { login } from "@/api/services/AuthService";
import type { LoginParams } from "@/api/services/AuthService";
import { useUserStore } from "@/stores";
import loginBg from "@/assets/login_bg.png";
import logoBrand from "@/assets/组 617@2x.png";

const LoginView = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { loading, run } = useApi({ successMessage: "登录成功" });
  const [loginForm] = Form.useForm();
  const fetchUserInfo = useUserStore((state) => state.fetchUserInfo);

  // 如果已登录，重定向到总览
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (token) {
      navigate("/", { replace: true });
    }
  }, [navigate]);

  // 处理登录
  const handleLogin = async (values: LoginParams) => {
    await run(async () => {
      const response = await login({
        username: values.username,
        password: values.password,
      });

      if (!response.data?.token) {
        throw new Error("登录失败，未返回有效凭证");
      }

      localStorage.setItem("token", response.data.token);
      if (response.data.user) {
        localStorage.setItem("userInfo", JSON.stringify(response.data.user));
      }
      await fetchUserInfo();
      const fromPath = (location.state as { from?: { pathname?: string } })?.from?.pathname;
      const to = fromPath && fromPath !== "/" ? fromPath : "/";
      navigate(to, { replace: true });
    });
  };

  return (
    <div className="login-container relative w-screen h-screen flex overflow-hidden">
      {/* 背景图 */}
      <div
        className="login-background absolute top-0 left-0 w-full h-full bg-cover bg-center bg-no-repeat z-0"
        style={{ backgroundImage: `url(${loginBg})` }}
      ></div>

      {/* 左侧品牌区域 */}
      <div className="flex-1 relative z-10 flex items-start p-[20px] py-[20px]">
        <div className="">
          <img src={logoBrand} alt="数据流动治理平台" className="h-[85px] w-auto" />
        </div>
      </div>

      {/* 右侧登录表单 */}
      <div className="flex-1 relative z-10 flex items-center justify-center p-10">
        <div className="login-card w-full max-w-[420px] bg-white rounded-lg pt-[68px] pb-12 px-10 shadow-lg">
          {/* 标题 */}
          <div className="justify-evenly w-full flex mb-[60px]">
            {["欢", "迎", "登", "录"].map((char, index) => (
              <div
                key={index}
                className="text-[28px] text-[#333] font-semibold"
              >
                {char}
              </div>
            ))}
          </div>

          {/* 登录表单 */}
          <Form
            form={loginForm}
            name="login"
            onFinish={handleLogin}
            className="login-form mb-[60px]"
            layout="vertical"
            size="large"
          >
            <Form.Item
              name="username"
              rules={[{ required: true, message: "请输入用户名" }]}
            >
              <Input
                prefix={<UserOutlined />}
                placeholder="请输入用户名"
                autoComplete="username"
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="请输入密码"
                autoComplete="current-password"
              />
            </Form.Item>

            <Form.Item className="mt-2">
              <Button
                type="primary"
                htmlType="submit"
                className="w-full h-11 text-base"
                loading={loading}
                style={{ backgroundColor: "#0080FF" }}
              >
                登录
              </Button>
            </Form.Item>
          </Form>
        </div>
      </div>
    </div>
  );
};

export default LoginView;
