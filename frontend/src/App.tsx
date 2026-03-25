import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { DashboardRouter } from "./components/DashboardRouter";
import { DashboardPage } from "./pages/DashboardPage";
import { Login } from "./pages/Login";
import { Onboarding } from "./pages/Onboarding";
import { SignUp } from "./pages/SignUp";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<SignUp />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/dashboard" element={<DashboardRouter />} />
        <Route path="/dashboard/legacy" element={<DashboardPage />} />
      </Routes>
    </BrowserRouter>
  );
}
