# Magic 🪄✨

Most scientists write lab control in scripts. It's fast, direct, and you don't need to be a software engineer. But scripts have limits. You want a GUI so someone can monitor while the experiment runs. You want a web dashboard for remote access. You want to run multiple tasks simultaneously without them interfering.

Each of these things should be possible without rewriting your entire control layer. LabDaemon makes it possible.

## What You Get

Write your device classes once. Use them in scripts, GUIs, web interfaces, or any combination simultaneously. The same device code works everywhere.

Write device-agnostic experiments that work with any hardware matching the interface. Swap laser models, DAQ cards, or cameras without changing measurement logic.

Multiple people and programs can safely use the same hardware at once. Call a device from a GUI while a script is running while a web client is monitoring—no conflicts, no crashes.

Real-time data streams from your devices work locally and over the web. A device that streams frames to a local callback automatically streams to web clients too.

You don't have to become a threading expert. No locks to reason about, no async/await patterns, no complex state management. Write straightforward Python.

## How It Works

Behind the scenes, LabDaemon handles the coordination problems that usually require careful engineering:

Thread coordination: Every call to a device automatically acquires that device's lock. Multiple threads can safely call the same device simultaneously—the framework serialises access. Your device code stays straightforward and synchronous.

Device lifecycle: Connect and disconnect happen automatically. You don't leak resources or leave instruments in bad states. This works whether you're in a script or a long-lived server process.

Multi-client coordination: When multiple interfaces (script, GUI, web) need the same hardware, the server layer enforces device ownership. Tasks declare which devices they need, the server grants exclusive access while the task runs, other clients get a clear "device is busy" response.

Streaming distribution: When real experiments run, you often want real-time data—live plots updating as you measure, progress indicators, or device cooperation based on measured data. Getting that data while your experiment runs usually requires complex threading or async code. LabDaemon provides streaming: devices push data to callbacks as it arrives, without blocking anything. Your measurement loop keeps running. Your GUI stays responsive & updates live. Locally you subscribe to callbacks directly. Through the server, the same streams become web endpoints (Server-Sent Events). The device code never changes.

You don't implement any of this—the framework does. But understanding what's happening in the background helps you structure code that scales well.

## The Result

You write straightforward Python that controls your instruments. You structure it in a way that works: devices are simple classes, tasks coordinate them, the daemon manages access. Then you never have to rewrite it. That same code works in scripts, GUIs, web interfaces, and distributed experiments.

This isn't about making coordination disappear—it's about doing the boring coordination work once, correctly, so you focus on your science rather than debugging software architecture.

Next, read [Concepts](concepts.md) to understand the five building blocks (devices, tasks, the daemon, streaming, and the server) and how to structure your code around them.
