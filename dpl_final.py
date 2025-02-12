import kagglehub
import pandas as pd
import os
import re
import nltk
from nltk.corpus import stopwords
from pymorphy3 import MorphAnalyzer
import spacy
from sklearn.utils import resample
import matplotlib

matplotlib.use('Agg')  # Устанавливаем неинтерактивный бэкенд для matplotlib
import matplotlib.pyplot as plt
from wordcloud import WordCloud
from sklearn.model_selection import train_test_split, GridSearchCV, RandomizedSearchCV, cross_val_score
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.pipeline import make_pipeline
from sklearn.metrics import (
    classification_report, f1_score, accuracy_score, precision_score, recall_score,
    roc_auc_score, confusion_matrix, auc, roc_curve
)
from sklearn.preprocessing import LabelEncoder, LabelBinarizer
from clearml import Task
from PIL import Image
from evidently.report import Report
from evidently.metric_preset import ClassificationPreset
from evidently.pipeline.column_mapping import ColumnMapping
import seaborn as sns
import numpy as np
from collections import Counter
from tabulate import tabulate  # Для красивого вывода таблиц

# Инициализация задачи ClearML
task = Task.init(
    project_name="Movie Reviews Classification",
    task_name="Model Comparison",
    tags=["NLP", "Model Comparison", "Logistic Regression", "Random Forest", "SVM"]
)

# Логирование параметров
task_params = {
    "test_size": 0.3,
    "random_state": 42,
    "cross_validation_folds": 3,
    "max_features": 10000,
    "max_iter": 1000,
    "solver": "saga"
}
task.connect(task_params)

# 1. Функция загрузки данных
def load_data():
    base_path = kagglehub.dataset_download("mikhailklemin/kinopoisks-movies-reviews")  # Загрузка данных с Kaggle
    categories = ['pos', 'neg', 'neu']  # Категории отзывов
    data = []
    for category in categories:
        folder_path = os.path.join(base_path + '/dataset', category)  # Путь к папке с отзывами
        for filename in os.listdir(folder_path):
            if filename.endswith('.txt'):  # Чтение только текстовых файлов
                with open(os.path.join(folder_path, filename), 'r', encoding='utf-8') as file:
                    review = file.read()  # Чтение текста отзыва
                    data.append((review, category))  # Добавление отзыва и его категории в список
    return pd.DataFrame(data, columns=['review', 'class'])  # Возвращение DataFrame с отзывами и их классами

# 2. Функция предобработки текста
def preprocess_data(df):
    nltk.download('stopwords')  # Загрузка стоп-слов для русского языка
    stop_words = set(stopwords.words('russian'))  # Инициализация стоп-слов
    morph = MorphAnalyzer()  # Инициализация морфологического анализатора

    def preprocess_text(text):
        text = re.sub(r'[^а-яА-ЯёЁ\s]', '', text)  # Удаление всех символов, кроме букв и пробелов
        text = re.sub(r'\s+', ' ', text)  # Удаление лишних пробелов
        text = text.lower()  # Приведение текста к нижнему регистру
        text = ' '.join(word for word in text.split() if word not in stop_words)  # Удаление стоп-слов
        text = ' '.join(morph.normal_forms(word)[0] for word in text.split())  # Лемматизация слов
        return text

    df['cleaned_review'] = df['review'].apply(preprocess_text)  # Применение функции предобработки к каждому отзыву
    df = df[df['cleaned_review'].str.strip() != '']  # Удаление пустых отзывов после предобработки

    if df.empty:
        raise ValueError("Все тексты стали пустыми после предобработки!")  # Проверка на пустоту DataFrame

    return df

# 3. Функция токенизации
def tokenize_data(df):
    nlp = spacy.load('ru_core_news_md')  # Загрузка модели для русского языка

    def tokenize_text(text):
        doc = nlp(text)  # Токенизация текста
        return [token.lemma_ for token in doc if not token.is_stop and not token.is_punct]  # Лемматизация и удаление стоп-слов и знаков препинания

    df['tokens'] = df['cleaned_review'].apply(tokenize_text)  # Применение функции токенизации к каждому отзыву
    return df

# 4. Функция балансировки данных
def balance_data(df):
    le = LabelEncoder()  # Инициализация LabelEncoder
    df['class'] = le.fit_transform(df['class'])  # Преобразование текстовых меток классов в числовые

    class_counts = df['class'].value_counts()  # Подсчет количества примеров в каждом классе
    min_class_size = min(class_counts)  # Определение минимального количества примеров в классе

    dfs = []
    for class_id in class_counts.index:
        dfs.append(
            resample(df[df['class'] == class_id],  # Балансировка данных путем уменьшения количества примеров в каждом классе до минимального
                     replace=False,
                     n_samples=min_class_size,
                     random_state=42)
        )

    return pd.concat(dfs)  # Возвращение сбалансированного DataFrame

# 5. Анализ частых слов
def analyze_top_words(df, n=10):
    class_names = {0: 'pos', 1: 'neg', 2: 'neu'}  # Словарь для преобразования числовых меток в текстовые
    for class_id, class_name in class_names.items():
        all_words = [word for tokens in df[df['class'] == class_id]['tokens'] for word in tokens]  # Сбор всех слов для каждого класса
        word_counts = Counter(all_words)  # Подсчет частоты слов
        print(f"\nТоп-{n} слов для класса {class_name}:")
        for word, count in word_counts.most_common(n):  # Вывод топ-N слов для каждого класса
            print(f"{word}: {count}")

# 6. Визуализация данных
def visualize_data(df, task):
    if df['cleaned_review'].empty:
        print("Нет данных для визуализации облака слов.")
        return

    all_words = ' '.join(df['cleaned_review'])  # Объединение всех отзывов в один текст
    wordcloud = WordCloud(width=800, height=400, background_color='white').generate(all_words)  # Создание облака слов
    output_file = "wordcloud.png"
    wordcloud.to_file(output_file)  # Сохранение облака слов в файл

    try:
        image = Image.open(output_file)  # Открытие изображения
        if image.mode == 'RGBA':
            image = image.convert('RGB')  # Преобразование изображения в RGB
        task.get_logger().report_image(
            title="Word Cloud",
            series="Balanced Dataset",
            image=image,
            iteration=0
        )  # Логирование изображения в ClearML
        print(f"Облако слов сохранено: {output_file}")
    except Exception as e:
        print(f"Ошибка при загрузке изображения: {e}")
    finally:
        if 'image' in locals():
            image.close()  # Закрытие изображения

# 7. Подготовка данных для обучения
def prepare_data(df):
    X = df['cleaned_review']  # Признаки (очищенные отзывы)
    y = df['class']  # Целевые метки

    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y,
        test_size=0.3,
        random_state=42,
        stratify=y
    )  # Разделение данных на обучающую и временную выборки
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp, y_temp,
        test_size=0.5,
        random_state=42,
        stratify=y_temp
    )  # Разделение временной выборки на валидационную и тестовую

    print(f'\nРазмеры выборок:')
    print(f'Обучающая: {X_train.shape[0]}')
    print(f'Валидационная: {X_val.shape[0]}')
    print(f'Тестовая: {X_test.shape[0]}')

    return X_train, X_val, X_test, y_train, y_val, y_test

# 8. Инициализация моделей
def initialize_models():
    return {
        "Logistic Regression": make_pipeline(
            TfidfVectorizer(max_features=10000),  # Векторизация текста с помощью TF-IDF
            LogisticRegression(random_state=42, solver='saga',
                               max_iter=1000, class_weight='balanced')  # Логистическая регрессия
        ),
        "Random Forest": make_pipeline(
            TfidfVectorizer(max_features=10000),
            RandomForestClassifier(random_state=42, n_estimators=100,
                                   class_weight='balanced', n_jobs=-1)  # Случайный лес
        ),
        "SVM": make_pipeline(
            TfidfVectorizer(max_features=10000),
            SVC(random_state=42, kernel='linear',
                class_weight='balanced', probability=True)  # Метод опорных векторов
        )
    }

# 9. Оптимизация гиперпараметров
def optimize_hyperparameters(model, param_grid, X_train, y_train,
                             cv=3, scoring='f1_weighted', search_type='grid'):
    if search_type == 'grid':
        search = GridSearchCV(model, param_grid, cv=cv,
                              scoring=scoring, n_jobs=-1)  # Поиск по сетке гиперпараметров
    else:
        search = RandomizedSearchCV(model, param_grid, cv=cv,
                                    scoring=scoring, n_jobs=-1,
                                    n_iter=10, random_state=42)  # Случайный поиск гиперпараметров
    search.fit(X_train, y_train)  # Обучение модели с поиском лучших гиперпараметров
    return search.best_estimator_, search.best_params_  # Возвращение лучшей модели и параметров

# 10. Оценка модели
def evaluate_model(model, X_train, y_train, X_test, y_test, le):
    # Кросс-валидация
    cv_scores = cross_val_score(model, X_train, y_train,
                                cv=3, scoring='f1_weighted')  # Оценка модели с помощью кросс-валидации
    print(f"\nСредний F1-score на кросс-валидации: {np.mean(cv_scores)}")

    # Предсказания
    y_test_pred = model.predict(X_test)  # Предсказание на тестовой выборке
    y_test_proba = model.predict_proba(X_test) if hasattr(model, "predict_proba") else None  # Вероятности классов

    # Вывод предсказаний в консоль
    print("\nПримеры предсказаний:")
    for i in range(min(10, len(X_test))):  # Выводим первые 10 предсказаний
        print(f"Текст: {X_test.iloc[i]}")
        print(f"Фактический класс: {le.inverse_transform([y_test.iloc[i]])[0]}")
        print(f"Предсказанный класс: {le.inverse_transform([y_test_pred[i]])[0]}")
        print("-" * 50)

    # Сохранение предсказаний в файл
    predictions_df = pd.DataFrame({
        'Текст': X_test,
        'Фактический класс': le.inverse_transform(y_test),
        'Предсказанный класс': le.inverse_transform(y_test_pred)
    })
    predictions_file = "predictions.csv"
    predictions_df.to_csv(predictions_file, index=False, encoding='utf-8')  # Сохранение предсказаний в CSV
    print(f"\nПредсказания сохранены в файл: {predictions_file}")

    # Расчет метрик
    metrics = {
        "CV F1": np.mean(cv_scores),
        "Test F1": f1_score(y_test, y_test_pred, average='weighted'),  # F1-score на тестовой выборке
        "Test Accuracy": accuracy_score(y_test, y_test_pred),  # Точность на тестовой выборке
        "Test Precision": precision_score(y_test, y_test_pred, average='weighted'),  # Точность (precision)
        "Test Recall": recall_score(y_test, y_test_pred, average='weighted'),  # Полнота (recall)
        "Test ROC-AUC": None
    }

    # ROC-AUC
    if y_test_proba is not None and y_test_proba.ndim > 1:
        lb = LabelBinarizer()
        y_test_bin = lb.fit_transform(y_test)
        try:
            metrics["Test ROC-AUC"] = roc_auc_score(y_test_bin, y_test_proba, multi_class='ovr')  # ROC-AUC для многоклассовой классификации
        except Exception as e:
            print(f"Ошибка вычисления ROC-AUC: {e}")

    # Матрица ошибок
    fig = plt.figure()
    sns.heatmap(confusion_matrix(y_test, y_test_pred),
                annot=True, fmt='d', cmap='Blues',
                xticklabels=le.classes_,
                yticklabels=le.classes_)  # Визуализация матрицы ошибок
    plt.title('Confusion Matrix')
    plt.xlabel('Predicted')
    plt.ylabel('Actual')
    plt.savefig("confusion_matrix.png")  # Сохранение матрицы ошибок в файл
    plt.close(fig)  # Закрытие фигуры

    # ROC-кривая
    if y_test_proba is not None and y_test_proba.ndim > 1:
        fig = plt.figure()
        for i in range(y_test_proba.shape[1]):
            fpr, tpr, _ = roc_curve((y_test == i).astype(int), y_test_proba[:, i])  # Расчет ROC-кривой для каждого класса
            roc_auc = auc(fpr, tpr)  # Расчет площади под ROC-кривой
            plt.plot(fpr, tpr, label=f'Class {le.classes_[i]} (AUC = {roc_auc:.2f})')  # Визуализация ROC-кривой
        plt.xlabel('False Positive Rate')
        plt.ylabel('True Positive Rate')
        plt.title('ROC Curve')
        plt.legend()
        plt.savefig("roc_curve.png")  # Сохранение ROC-кривой в файл
        plt.close(fig)  # Закрытие фигуры

    metrics["Classification Report"] = classification_report(y_test, y_test_pred, output_dict=True)  # Отчет классификации
    return metrics

# 11. Логирование метрик в ClearML
def log_metrics(task, model_name, metrics):
    # Скалярные метрики
    task.get_logger().report_scalar(title="F1-score (CV)", series=model_name, value=metrics["CV F1"], iteration=0)
    task.get_logger().report_scalar(title="F1-score (Test)", series=model_name, value=metrics["Test F1"], iteration=0)
    task.get_logger().report_scalar(title="Accuracy (Test)", series=model_name, value=metrics["Test Accuracy"],
                                    iteration=0)
    task.get_logger().report_scalar(title="Precision (Test)", series=model_name, value=metrics["Test Precision"],
                                    iteration=0)
    task.get_logger().report_scalar(title="Recall (Test)", series=model_name, value=metrics["Test Recall"], iteration=0)

    if metrics["Test ROC-AUC"] is not None:
        task.get_logger().report_scalar(title="ROC-AUC (Test)", series=model_name, value=metrics["Test ROC-AUC"],
                                        iteration=0)

    # Отчет классификации
    task.get_logger().report_table(
        title=f"Classification Report (Test) - {model_name}",
        series="Model Comparison",
        table_plot=pd.DataFrame(metrics["Classification Report"]).transpose(),
        iteration=0
    )

# 12. Сравнение моделей
def plot_comparison(results):
    metrics = ['Test F1', 'Test Accuracy', 'Test Precision', 'Test Recall', 'Test ROC-AUC']
    model_names = list(results.keys())

    # Создаем таблицу для вывода в консоль
    table = []
    for model_name in model_names:
        row = [model_name]
        for metric in metrics:
            value = results[model_name].get(metric, "N/A")  # Если метрика отсутствует, выводим "N/A"
            row.append(round(value, 4) if isinstance(value, (int, float)) else value)
        table.append(row)

    # Выводим таблицу в консоль
    print("\nСравнение моделей по метрикам:")
    print(tabulate(table, headers=["Модель"] + metrics, tablefmt="pretty"))

    # Визуализация графиков (столбчатая диаграмма)
    fig, ax = plt.subplots(figsize=(12, 8))
    x = np.arange(len(model_names))  # Позиции для моделей
    width = 0.15  # Ширина столбцов

    for i, metric in enumerate(metrics):
        values = [results[model][metric] or 0 for model in model_names]
        bars = ax.bar(x + i * width, values, width, label=metric)

        # Добавляем значения метрик сверху столбцов
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.2f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),  # Смещение текста относительно столбца
                        textcoords="offset points",
                        ha='center', va='bottom')

    ax.set_xlabel('Модели')
    ax.set_ylabel('Значение метрики')
    ax.set_title('Сравнение моделей по метрикам')
    ax.set_xticks(x + width * (len(metrics) - 1) / 2)
    ax.set_xticklabels(model_names)
    ax.legend(loc='upper left', bbox_to_anchor=(1, 1))  # Легенда справа от графика
    plt.grid(True)

    # Сохраняем график в файл
    output_file = "model_comparison_metrics.png"
    plt.savefig(output_file, bbox_inches='tight')  # Сохраняем график в файл
    plt.close(fig)  # Закрываем фигуру
    print(f"График сравнения моделей сохранен: {output_file}")  # Сообщение в консоль

    # Логирование в ClearML
    try:
        image = Image.open(output_file)
        if image.mode == 'RGBA':
            image = image.convert('RGB')
        task.get_logger().report_image(
            title="Model Comparison",
            series="Final Results",
            image=image,
            iteration=0
        )
        image.close()
    except Exception as e:
        print(f"Ошибка при загрузке изображения: {e}")

# Основной пайплайн выполнения
def main():
    # Загрузка и обработка данных
    df = load_data()
    print("Данные загружены:")
    print(df.tail())

    df = preprocess_data(df)
    print("\nДанные после предобработки:")
    print(df['cleaned_review'].tail())

    df = tokenize_data(df)
    print("\nДанные после токенизации:")
    print(df['tokens'].tail())

    df_balanced = balance_data(df)
    print("\nРаспределение классов после балансировки:")
    print(df_balanced['class'].value_counts())

    # Анализ и визуализация
    analyze_top_words(df_balanced)
    visualize_data(df_balanced, task)
    task.upload_artifact("Balanced Dataset", df_balanced)

    # Подготовка данных
    X_train, X_val, X_test, y_train, y_val, y_test = prepare_data(df_balanced)
    le = LabelEncoder().fit(y_train)

    # Инициализация моделей
    models = initialize_models()

    # Параметры для оптимизации
    param_grids = {
        "Logistic Regression": {
            'logisticregression__C': [0.01, 0.1, 1, 10, 100],
            'logisticregression__solver': ['liblinear', 'lbfgs']
        },
        "Random Forest": {
            'randomforestclassifier__n_estimators': [50, 100, 200],
            'randomforestclassifier__max_depth': [None, 10, 20, 30]
        },
        "SVM": {
            'svc__C': [0.01, 0.1, 1, 10, 100],
            'svc__kernel': ['linear', 'rbf']
        }
    }

    # Обучение и оценка моделей
    results = {}
    trained_models = {}  # Сюда сохраняем обученные модели

    for model_name in models:
        print(f"\n{'=' * 40}\nОбработка модели: {model_name}\n{'=' * 40}")

        # Оптимизация гиперпараметров
        best_model, best_params = optimize_hyperparameters(
            models[model_name],
            param_grids[model_name],
            X_train, y_train,
            search_type='grid' if model_name == "Logistic Regression" else 'random'
        )

        # Обучение модели на всей обучающей выборке
        best_model.fit(X_train, y_train)
        trained_models[model_name] = best_model  # Сохраняем обученную модель

        # Оценка модели
        metrics = evaluate_model(best_model, X_train, y_train, X_test, y_test, le)
        results[model_name] = metrics

        # Логирование
        task.get_logger().report_text(f"Лучшие параметры для {model_name}: {best_params}")
        log_metrics(task, model_name, metrics)

    # Сравнение моделей
    plot_comparison(results)

    # Анализ дрейфа данных
    df_balanced_for_evidently = df_balanced.drop(columns=['tokens'])

    # Используем обученную модель для предсказаний
    df_balanced_for_evidently['prediction'] = trained_models["Logistic Regression"].predict(
        df_balanced['cleaned_review']
    )

    column_mapping = ColumnMapping(
        target='class',
        prediction='prediction',
        text_features=['cleaned_review']
    )

    report = Report(metrics=[ClassificationPreset()])
    report.run(
        reference_data=df_balanced_for_evidently.sample(frac=0.5, random_state=42),
        current_data=df_balanced_for_evidently.sample(frac=0.5, random_state=24),
        column_mapping=column_mapping
    )
    report.save_html("classification_report.html")
    print("\nОтчет: classification_report.html сохранен.")
    task.upload_artifact("Classification Report", "classification_report.html")

if __name__ == "__main__":
    main()
    task.close()