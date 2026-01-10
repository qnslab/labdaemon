# Tasks

Tasks orchestrate experiments by coordinating multiple devices. They run in background threads, keeping your application responsive while long measurements execute. A task is just a class with a run method that receives a context object.

## When to Use Tasks vs Scripts

Tasks return immediately, as the function is run in a separate thread. They are slightly harder to write, but really very simple. In particular if you are just starting out, you might write your experiment logic in plain scripts - this is often fine. But we recommend moving to Tasks early on (especially for any operation >1 second), as you immediately get the full capabilities of labdaemon (GUI, server, cancellation, ...), without losing composability, reusability etc.

## Topics

Select a topic from the sidebar to learn more about tasks:
- [Task Basics](task-basics.md): Core concepts and basic task creation
- [Device-Agnostic Tasks](device-agnostic-tasks.md): Writing hardware-independent experiments
- [Task Composition](composition.md): Combining and coordinating multiple tasks
- [Multi-Device Coordination](multi-device-coordination.md): Coordinating multiple devices
- [Interactive Tasks](interactive.md): Building tasks that can be paused, resumed, and parameterized
- [Task Progress Streaming](streaming.md): Streaming progress updates from running tasks