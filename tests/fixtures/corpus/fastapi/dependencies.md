# Dependencies

Declare a dependency by adding a parameter with `Depends(get_db)` to a path operation.

## Caching

Within one request, a dependency used several times is called once unless `use_cache=False`.

```python
# not a heading
async def get_db():
    yield session
```
