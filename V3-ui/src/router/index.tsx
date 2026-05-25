import { createBrowserRouter, Navigate } from "react-router-dom";
import App from "@/App";
import LoginView from "@/views/LoginView";
import NavPlaceholder from "@/views/NavPlaceholder";
import RiskTaskList from "@/views/risk/RiskTaskList";
import RiskDetailPlaceholder from "@/views/risk/RiskDetailPlaceholder";
import ProtectedRoute from "@/components/ProtectedRoute";

export const router = createBrowserRouter([
    {
        path: "/login",
        element: <LoginView />,
    },
    {
        path: "/",
        element: (
            <ProtectedRoute>
                <App />
            </ProtectedRoute>
        ),
        children: [
            {
                index: true,
                element: <NavPlaceholder title="总览" layout="risk" />,
            },
            {
                path: "posture",
                element: <NavPlaceholder title="态势" />,
            },
            {
                path: "property",
                element: <NavPlaceholder title="资产" />,
            },
            {
                path: "user",
                element: <NavPlaceholder title="用户" />,
            },
            {
                path: "audit",
                element: <NavPlaceholder title="审计" />,
            },
            {
                path: "risk",
                element: <RiskTaskList />,
            },
            {
                path: "risk/detail",
                element: <RiskDetailPlaceholder />,
            },
            {
                path: "governance",
                element: <NavPlaceholder title="治理" />,
            },
            {
                path: "tactics",
                element: <NavPlaceholder title="策略" />,
            },
            {
                path: "setting",
                element: <NavPlaceholder title="设置" layout="risk" />,
            },
            {
                path: "lab",
                element: <NavPlaceholder title="实验室" />,
            },
        ],
    },
    {
        path: "*",
        element: <Navigate to="/" replace />,
    },
]);
