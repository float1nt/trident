import { createBrowserRouter, Navigate } from "react-router-dom";
import App from "@/App";
import LoginView from "@/views/LoginView";
import NavPlaceholder from "@/views/NavPlaceholder";
import ProtectedRoute from "@/components/ProtectedRoute";
import RiskLayout from "@/modules/risk/RiskLayout";
import RunsComparePage from "@/modules/risk/pages/RunsComparePage";
import GraphAnalysisPage from "@/modules/risk/pages/GraphAnalysisPage";
import LearnerDetailPage from "@/modules/risk/pages/LearnerDetailPage";
import { riskPaths } from "@/modules/risk/riskPaths";

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
                element: <NavPlaceholder title="首页" />,
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
                element: <RiskLayout />,
                children: [
                    {
                        index: true,
                        element: <Navigate to={riskPaths.runsCompare} replace />,
                    },
                    {
                        path: "runs-compare",
                        element: <RunsComparePage />,
                    },
                    {
                        path: "run-detail",
                        element: <GraphAnalysisPage />,
                    },
                    {
                        path: "learner-detail",
                        element: <LearnerDetailPage />,
                    },
                    {
                        path: "learner-detail/:runId",
                        element: <LearnerDetailPage />,
                    },
                    {
                        path: "graph-analysis",
                        element: <Navigate to={riskPaths.runDetail} replace />,
                    },
                    {
                        path: "run/:runId",
                        element: <GraphAnalysisPage />,
                    },
                ],
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
                element: <NavPlaceholder title="设置" />,
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
