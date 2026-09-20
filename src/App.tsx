import { BrowserRouter, Routes, Route } from "react-router-dom";
import ScannerPage from "./pages/ScannerPage";
import StockAnalysisPage from "./pages/StockAnalysisPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ScannerPage />} />
        <Route path="/analysis/:symbol" element={<StockAnalysisPage />} />
      </Routes>
    </BrowserRouter>
  );
}
