'use client';

import { useState } from 'react';

interface CreateCaseFormData {
  title: string;
  description: string;
  budget_expectation_rub: number;
  region: string;
  attachments?: string[];
}

export default function CreateCaseForm() {
  const [formData, setFormData] = useState<CreateCaseFormData>({
    title: '',
    description: '',
    budget_expectation_rub: 100000,
    region: '',
    attachments: [],
  });
  
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      const token = localStorage.getItem('access_token');
      
      const response = await fetch('http://localhost:8000/api/client/cases', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify(formData),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Ошибка при создании дела');
      }

      const result = await response.json();
      setSuccess(`Дело успешно создано! ID: ${result.case_id}`);
      
      // Очистить форму
      setFormData({
        title: '',
        description: '',
        budget_expectation_rub: 100000,
        region: '',
        attachments: [],
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-6 bg-white rounded-lg shadow-md">
      <h2 className="text-2xl font-bold mb-6">Создать новое дело</h2>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Название */}
        <div>
          <label className="block text-sm font-medium mb-2">
            Название дела *
          </label>
          <input
            type="text"
            required
            minLength={5}
            maxLength={200}
            value={formData.title}
            onChange={(e) => setFormData({ ...formData, title: e.target.value })}
            className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
            placeholder="Например: Консультация по трудовому договору"
          />
        </div>

        {/* Описание */}
        <div>
          <label className="block text-sm font-medium mb-2">
            Описание проблемы *
          </label>
          <textarea
            required
            minLength={20}
            maxLength={5000}
            rows={6}
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
            placeholder="Подробно опишите вашу ситуацию..."
          />
        </div>

        {/* Бюджет */}
        <div>
          <label className="block text-sm font-medium mb-2">
            Ожидаемый бюджет (₽) *
          </label>
          <input
            type="number"
            required
            min={1}
            value={formData.budget_expectation_rub}
            onChange={(e) => setFormData({ ...formData, budget_expectation_rub: Number(e.target.value) })}
            className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* Регион */}
        <div>
          <label className="block text-sm font-medium mb-2">
            Регион *
          </label>
          <input
            type="text"
            required
            minLength={2}
            maxLength={100}
            value={formData.region}
            onChange={(e) => setFormData({ ...formData, region: e.target.value })}
            className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
            placeholder="Например: Москва"
          />
        </div>

        {/* Сообщения об ошибках/успехе */}
        {error && (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
            {error}
          </div>
        )}
        
        {success && (
          <div className="p-4 bg-green-50 border border-green-200 rounded-lg text-green-700">
            {success}
          </div>
        )}

        {/* Кнопка отправки */}
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
        >
          {loading ? 'Создание...' : 'Создать дело'}
        </button>
      </form>
    </div>
  );
}
