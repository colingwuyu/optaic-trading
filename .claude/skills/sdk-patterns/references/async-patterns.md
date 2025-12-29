# Async Operations Patterns

## Long-Running Operations

Runs and backtests are long-running; provide polling helpers:

```python
import time
from typing import Callable, Optional

class RunsMixin:
    def run_and_wait(
        self,
        instance_id: UUID,
        params: Optional[dict] = None,
        timeout: float = 3600,  # 1 hour default
        poll_interval: float = 5.0,
        on_status: Optional[Callable[[Run], None]] = None
    ) -> Run:
        """
        Submit run and wait for completion.

        Args:
            instance_id: Instance to run
            params: Run parameters
            timeout: Max wait time in seconds
            poll_interval: Seconds between status checks
            on_status: Callback on each status check

        Returns:
            Completed run

        Raises:
            TimeoutError: If timeout exceeded
            RunFailedError: If run failed
        """
        run = self.submit_run(instance_id, params)
        start = time.time()

        while True:
            run = self.get_run(run.id)

            if on_status:
                on_status(run)

            if run.status == "completed":
                return run

            if run.status == "failed":
                raise RunFailedError(run.error_message, run)

            if run.status == "cancelled":
                raise RunCancelledError("Run was cancelled", run)

            elapsed = time.time() - start
            if elapsed > timeout:
                raise TimeoutError(f"Run did not complete within {timeout}s")

            time.sleep(poll_interval)


class AsyncRunsMixin:
    async def run_and_wait(
        self,
        instance_id: UUID,
        params: Optional[dict] = None,
        timeout: float = 3600,
        poll_interval: float = 5.0,
        on_status: Optional[Callable[[Run], None]] = None
    ) -> Run:
        """Async version of run_and_wait."""
        import asyncio

        run = await self.submit_run(instance_id, params)
        start = time.time()

        while True:
            run = await self.get_run(run.id)

            if on_status:
                on_status(run)

            if run.status == "completed":
                return run

            if run.status in ("failed", "cancelled"):
                raise RunFailedError(run.error_message, run)

            if time.time() - start > timeout:
                raise TimeoutError()

            await asyncio.sleep(poll_interval)
```

## Upload with Progress

```python
from typing import Callable, BinaryIO
import io

ProgressCallback = Callable[[int, int], None]  # (bytes_sent, total_bytes)

class UploadMixin:
    def upload_data(
        self,
        dataset_id: UUID,
        file: BinaryIO,
        filename: str,
        on_progress: Optional[ProgressCallback] = None
    ) -> dict:
        """
        Upload data file to dataset.

        Args:
            dataset_id: Target dataset
            file: File-like object to upload
            filename: Name for the file
            on_progress: Progress callback (bytes_sent, total_bytes)

        Returns:
            Upload result with version info
        """
        # Get file size
        file.seek(0, 2)
        total_size = file.tell()
        file.seek(0)

        # Wrap file for progress tracking
        if on_progress:
            file = ProgressReader(file, total_size, on_progress)

        response = self._client.post(
            f"/api/v1/datasets/{dataset_id}/upload",
            files={"file": (filename, file)},
            timeout=600.0  # 10 min for large files
        )
        self._handle_response(response)
        return response.json()

    def upload_dataframe(
        self,
        dataset_id: UUID,
        df,  # pandas.DataFrame
        on_progress: Optional[ProgressCallback] = None
    ) -> dict:
        """
        Upload pandas DataFrame as parquet.

        Requires: pip install optaic[data]
        """
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            raise ImportError(
                "DataFrame upload requires pyarrow. "
                "Install with: pip install optaic[data]"
            )

        buffer = io.BytesIO()
        table = pa.Table.from_pandas(df)
        pq.write_table(table, buffer, compression="snappy")
        buffer.seek(0)

        return self.upload_data(
            dataset_id,
            buffer,
            "data.parquet",
            on_progress
        )


class ProgressReader:
    """Wrapper that tracks read progress."""

    def __init__(
        self,
        file: BinaryIO,
        total_size: int,
        callback: ProgressCallback
    ):
        self._file = file
        self._total = total_size
        self._sent = 0
        self._callback = callback

    def read(self, size: int = -1) -> bytes:
        data = self._file.read(size)
        self._sent += len(data)
        self._callback(self._sent, self._total)
        return data

    def seek(self, *args):
        return self._file.seek(*args)

    def tell(self):
        return self._file.tell()
```

## Download Operations

```python
class DownloadMixin:
    def download_data(
        self,
        dataset_id: UUID,
        version_id: Optional[UUID] = None,
        on_progress: Optional[ProgressCallback] = None
    ) -> bytes:
        """
        Download dataset data.

        Args:
            dataset_id: Dataset to download
            version_id: Specific version (None = latest)
            on_progress: Progress callback

        Returns:
            Raw file bytes
        """
        url = f"/api/v1/datasets/{dataset_id}/download"
        if version_id:
            url += f"?version_id={version_id}"

        with self._client.stream("GET", url) as response:
            self._handle_response(response)

            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            chunks = []

            for chunk in response.iter_bytes():
                chunks.append(chunk)
                downloaded += len(chunk)
                if on_progress and total:
                    on_progress(downloaded, total)

            return b"".join(chunks)

    def download_dataframe(
        self,
        dataset_id: UUID,
        version_id: Optional[UUID] = None
    ):
        """
        Download as pandas DataFrame.

        Requires: pip install optaic[data]
        """
        try:
            import pandas as pd
            import pyarrow.parquet as pq
        except ImportError:
            raise ImportError("Install with: pip install optaic[data]")

        data = self.download_data(dataset_id, version_id)
        buffer = io.BytesIO(data)
        return pd.read_parquet(buffer)
```

## Streaming Results

For large result sets:

```python
class StreamingMixin:
    def stream_query_results(
        self,
        dataset_id: UUID,
        query: str,
        chunk_size: int = 10000
    ):
        """
        Stream query results in chunks.

        Yields:
            DataFrames of chunk_size rows
        """
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("Install with: pip install optaic[data]")

        offset = 0
        while True:
            response = self._client.post(
                f"/api/v1/datasets/{dataset_id}/query",
                json={
                    "query": query,
                    "limit": chunk_size,
                    "offset": offset
                }
            )
            self._handle_response(response)

            data = response.json()
            if not data["rows"]:
                break

            yield pd.DataFrame(data["rows"], columns=data["columns"])

            if len(data["rows"]) < chunk_size:
                break

            offset += chunk_size
```

## Lazy Import Pattern

Heavy dependencies must be lazy-loaded:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    import pyarrow as pa
    import numpy as np


def upload_dataframe(self, dataset_id: UUID, df):
    """Upload with lazy imports."""
    try:
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:
        raise ImportError(
            f"Missing dependency: {e.name}. "
            "Install with: pip install optaic[data]"
        )

    # Now safe to use pandas/pyarrow
    buffer = io.BytesIO()
    table = pa.Table.from_pandas(df)
    pq.write_table(table, buffer)
    buffer.seek(0)
    return self._upload(dataset_id, buffer)
```
