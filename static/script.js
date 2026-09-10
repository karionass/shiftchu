document.addEventListener('DOMContentLoaded', function() {
    const rawTasks = window.tasks || [];

    // Подготовка событий для календаря
    const events = rawTasks
        .filter(t => t.start)
        .map(t => ({
            id: String(t.id),
            title: t.title,
            start: t.start,
            color: t.completed == 1 ? "#28a745" : t.overdue ? "#dc3545" : "#007bff"
        }));

    // Инициализация календаря
    const calendarEl = document.getElementById('calendar');
    if (calendarEl) {
        const calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            locale: 'ru',
            height: 'auto',
            editable: true,
            events: events,
            eventDrop: async function(info) {
                const taskId = info.event.id;
                const newDate = info.event.startStr; 

                try {
                    const res = await fetch(`/update-date/${taskId}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ deadline: newDate })
                    });
                    if (!res.ok) throw new Error("Ошибка при обновлении даты");
                    showAlert(`Дата задачи "${info.event.title}" обновлена!`);
                } catch(err) {
                    showAlert(err.message);
                    info.revert();
                }
            },
            eventClick: function(info) {
                const task = rawTasks.find(t => String(t.id) === String(info.event.id));
                if (!task) return;

                const modal = document.getElementById("taskModal");
                if (!modal) return;

                modal.style.display = "flex";
                modal.dataset.taskId = task.id;

                const titleText = task.raw_title !== undefined ? task.raw_title : task.title;
                const subject = task.note !== undefined ? task.note : "";

                document.getElementById("modalTitle").value = titleText;
                document.getElementById("modalSubject").value = subject;
                document.getElementById("modalDeadline").value = task.start ? task.start.split('T')[0] : "";
            }
        });
        calendar.render();
    }

document.addEventListener('click', async function(e) {
    const target = e.target;

    // Кнопка "выполнено" оставляем
    const doneBtn = target.closest('.btn-done');
    if (doneBtn) {
        e.preventDefault();
        const taskId = doneBtn.dataset.id;
        try {
            const res = await fetch(`/complete/${taskId}`, { method: 'POST' });
            if (res.ok) {
                const li = doneBtn.closest('li');
                if (li) li.remove();
                showAlert("Задача выполнена!");
            } else {
                showAlert("Ошибка при выполнении задачи");
            }
        } catch(err) {
            showAlert("Ошибка при выполнении задачи");
        }
        return;
    }
const deleteBtn = target.closest('.btn-delete, #deleteBtn');
if (deleteBtn) {
    e.preventDefault();
    let taskId;

    // определяем taskId
    if (deleteBtn.dataset.id) {
        taskId = deleteBtn.dataset.id;
    } else {
        const modal = document.getElementById("taskModal");
        taskId = modal?.dataset.taskId;
    }

    try {
        const res = await fetch(`/delete/${taskId}`, { method: 'POST' });
        if (res.ok) {
            // удаляем элемент из списка или таблицы
            const li = document.querySelector(`.btn-done[data-id='${taskId}']`)?.closest('li');
            const tr = document.querySelector(`.btn-delete[data-id='${taskId}']`)?.closest('tr');
            if (li) li.remove();
            if (tr) tr.remove();

            showAlert("Задача удалена!");

            // закрываем модальные окна
            const modal1 = document.getElementById("taskModal");
            if (modal1) modal1.style.display = 'none';
            const modal2 = document.getElementById("tasksModal");
            if (modal2) modal2.style.display = 'none';
        } else {
            showAlert("Ошибка при удалении задачи");
        }
    } catch(err) {
        showAlert("Ошибка при удалении задачи");
    }

    return;
}

});


    const modalForm = document.getElementById("modalForm");
    if (modalForm) {
        modalForm.addEventListener("submit", async function(e) {
            e.preventDefault();
            const modal = document.getElementById("taskModal");
            const id = modal.dataset.taskId;

            const data = {
                title: document.getElementById("modalTitle").value,
                subject: document.getElementById("modalSubject").value,
                deadline: document.getElementById("modalDeadline").value
            };

            try {
                const res = await fetch(`/edit/${id}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(data)
                });
                if (res.ok) location.reload();
                else showAlert("Ошибка при сохранении изменений");
            } catch(err) {
                showAlert("Ошибка при сохранении изменений");
            }
        }); 
    }
});
function toggleTasks() {
    const taskList = document.getElementById("task-list");
    const arrow = document.getElementById("toggle-arrow");

    if (!taskList) return;

    if (taskList.style.maxHeight && taskList.style.maxHeight !== "0px") {
        taskList.style.maxHeight = "0px";
        taskList.style.opacity = "0";
        arrow.textContent = "▲";
    } else {
        taskList.style.maxHeight = taskList.scrollHeight + "px";
        taskList.style.opacity = "1";
        arrow.textContent = "▼";
    }
}

// Кастомный алерт
function showAlert(message) {
    const existingAlert = document.querySelector('.custom-alert');
    if (existingAlert) existingAlert.remove();

    const alertBox = document.createElement('div');
    alertBox.className = 'custom-alert';
    alertBox.textContent = message;
    document.body.appendChild(alertBox);

    setTimeout(() => alertBox.classList.add('visible'), 50);
    setTimeout(() => {
        alertBox.classList.remove('visible');
        setTimeout(() => alertBox.remove(), 300);
    }, 2000);
}

const pet = createSitePet('example'); 
pet.id = 'sitePet'; 

pet.style.left = (window.innerWidth - 100) + 'px'; 
pet.style.top = (window.innerHeight - 100) + 'px';

// создаём элемент для текста
const bubble = document.createElement('div');
bubble.id = 'pet-speech';
pet.appendChild(bubble);

const messages = [
  "Дальше - меньше",
  "Ты самый слабый из всех кого я знаю!",
  "Будут проблемы - звони, я сброшу",
  "Ни шагу вперёд",
  "Не старайся, бросай всё"
];

function sayMessage(text) {
  bubble.innerText = text;
  bubble.style.opacity = 1;
  setTimeout(() => bubble.style.opacity = 0, 6000);
}

// показываем текст при клике
pet.addEventListener('click', () => {
  const msg = messages[Math.floor(Math.random() * messages.length)];
  sayMessage(msg);
});

// случайные фразы каждые 15–25 секунд
setInterval(() => {
  const msg = messages[Math.floor(Math.random() * messages.length)];
  sayMessage(msg);
}, Math.random() * 10000 + 15000);

// const toggleBtn = document.getElementById('themeToggle');
// toggleBtn.addEventListener('click', () => {
//     document.body.classList.toggle('dark-theme');

//     if(document.body.classList.contains('dark-theme')){
//         localStorage.setItem('theme', 'dark');
//     } else {
//         localStorage.setItem('theme', 'light');
//     }
// });

// window.addEventListener('DOMContentLoaded', () => {
//     if(localStorage.getItem('theme') === 'dark'){
//         document.body.classList.add('dark-theme');
//     }
// });
