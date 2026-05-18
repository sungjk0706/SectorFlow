# backend/app/di/container.py
# DI Container - 단일 인스턴스 관리

from typing import Any, Dict, Type, TypeVar, cast, get_type_hints
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class Container:
    """단일 인스턴스 DI Container"""
    
    _instance: 'Container | None' = None
    _services: Dict[Type[Any], Any] = {}
    _singletons: Dict[str, Any] = {}
    
    def __new__(cls) -> 'Container':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def register_singleton(self, name: str, instance: Any) -> None:
        """싱글톤 인스턴스 등록"""
        self._singletons[name] = instance
        logger.info(f"[DI Container] 싱글톤 등록: {name}")
    
    def get_singleton(self, name: str) -> Any:
        """싱글톤 인스턴스 조회"""
        if name not in self._singletons:
            raise ValueError(f"싱글톤 인스턴스 없음: {name}")
        return self._singletons[name]
    
    def register_service(self, service_type: Type[T], instance: T) -> None:
        """서비스 타입으로 인스턴스 등록"""
        self._services[service_type] = instance
        logger.info(f"[DI Container] 서비스 등록: {service_type.__name__}")
    
    def get_service(self, service_type: Type[T]) -> T:
        """서비스 타입으로 인스턴스 조회"""
        if service_type not in self._services:
            raise ValueError(f"서비스 인스턴스 없음: {service_type.__name__}")
        return cast(T, self._services[service_type])
    
    def has_singleton(self, name: str) -> bool:
        """싱글톤 인스턴스 존재 확인"""
        return name in self._singletons
    
    def has_service(self, service_type: Type[T]) -> bool:
        """서비스 인스턴스 존재 확인"""
        return service_type in self._services


# 전역 컨테이너 인스턴스
_container: Container | None = None


def get_container() -> Container:
    """전역 컨테이너 인스턴스 조회"""
    global _container
    if _container is None:
        _container = Container()
    return _container


def reset_container() -> None:
    """컨테이너 리셋 (테스트용)"""
    global _container
    _container = None
